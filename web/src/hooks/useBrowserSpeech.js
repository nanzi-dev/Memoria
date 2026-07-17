import { useCallback, useEffect, useRef, useState } from 'react';
import { speechApi } from '../api/memoria';

const MAX_RECORDING_MS = 60_000;
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
];

function audioKey({ mode, sessionId, messageId }) {
  return `${mode}:${sessionId}:${messageId}`;
}

function fileExtension(mimeType) {
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
}

function audioBufferToWavBlob(audioBuffer) {
  const channelCount = Math.min(audioBuffer.numberOfChannels, 2);
  const sampleCount = audioBuffer.length;
  const bytesPerSample = 2;
  const blockAlign = channelCount * bytesPerSample;
  const buffer = new ArrayBuffer(44 + sampleCount * blockAlign);
  const view = new DataView(buffer);
  const writeText = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };

  writeText(0, 'RIFF');
  view.setUint32(4, 36 + sampleCount * blockAlign, true);
  writeText(8, 'WAVE');
  writeText(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channelCount, true);
  view.setUint32(24, audioBuffer.sampleRate, true);
  view.setUint32(28, audioBuffer.sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeText(36, 'data');
  view.setUint32(40, sampleCount * blockAlign, true);

  const channels = Array.from(
    { length: channelCount },
    (_, index) => audioBuffer.getChannelData(index),
  );
  let offset = 44;
  for (let sample = 0; sample < sampleCount; sample += 1) {
    for (const channel of channels) {
      const value = Math.max(-1, Math.min(1, channel[sample]));
      view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
      offset += bytesPerSample;
    }
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

async function convertToWav(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return blob;
  const context = new AudioContextClass();
  try {
    const source = await blob.arrayBuffer();
    const audioBuffer = await context.decodeAudioData(source);
    return audioBufferToWavBlob(audioBuffer);
  } finally {
    await context.close?.();
  }
}

function recorderErrorMessage(error) {
  if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') {
    return '麦克风权限被拒绝，请在浏览器设置中允许访问';
  }
  if (error?.name === 'NotFoundError') return '未检测到可用麦克风';
  if (error?.name === 'NotReadableError') return '麦克风正被其他应用占用';
  return error?.message || '无法启动录音';
}

export default function useBrowserSpeech({ sessionId, mode, onTranscription } = {}) {
  const [speechStatus, setSpeechStatus] = useState('idle');
  const [speechError, setSpeechError] = useState(null);
  const [audioStates, setAudioStates] = useState({});

  const mountedRef = useRef(true);
  const onTranscriptionRef = useRef(onTranscription);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const recordingTimerRef = useRef(null);
  const recordingGenerationRef = useRef(0);
  const recordingContextRef = useRef(null);
  const transcriptionAbortRef = useRef(null);

  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const activeAudioRef = useRef(null);
  const audioRequestRef = useRef(0);
  const audioAbortRef = useRef(null);
  const playbackResolverRef = useRef(null);
  const autoplayQueueRef = useRef([]);
  const autoplayGenerationRef = useRef(0);
  const autoplayRunningRef = useRef(null);

  onTranscriptionRef.current = onTranscription;

  const setMessageAudioState = useCallback((descriptor, status, error = null) => {
    if (!mountedRef.current) return;
    const key = audioKey(descriptor);
    setAudioStates(current => ({
      ...current,
      [key]: { status, error },
    }));
  }, []);

  const stopMediaTracks = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach(track => track.stop());
    mediaStreamRef.current = null;
    if (recordingTimerRef.current) clearTimeout(recordingTimerRef.current);
    recordingTimerRef.current = null;
  }, []);

  const cancelRecording = useCallback(() => {
    recordingGenerationRef.current += 1;
    transcriptionAbortRef.current?.abort();
    transcriptionAbortRef.current = null;
    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    recordingChunksRef.current = [];
    recordingContextRef.current = null;
    if (recorder?.state && recorder.state !== 'inactive') {
      try { recorder.stop(); } catch {}
    }
    stopMediaTracks();
    if (mountedRef.current) {
      setSpeechStatus('idle');
      setSpeechError(null);
    }
  }, [stopMediaTracks]);

  const settlePlayback = useCallback((playedToEnd = false) => {
    const resolve = playbackResolverRef.current;
    playbackResolverRef.current = null;
    resolve?.(playedToEnd);
  }, []);

  const cancelAutoplayQueue = useCallback(() => {
    autoplayGenerationRef.current += 1;
    autoplayQueueRef.current = [];
  }, []);

  const releaseAudio = useCallback(({ resetState = true, clearQueue = false } = {}) => {
    audioRequestRef.current += 1;
    audioAbortRef.current?.abort();
    audioAbortRef.current = null;
    if (clearQueue) cancelAutoplayQueue();

    const audio = audioRef.current;
    if (audio) {
      audio.onplay = null;
      audio.onpause = null;
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }

    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = null;

    const active = activeAudioRef.current;
    activeAudioRef.current = null;
    if (active && resetState) setMessageAudioState(active, 'idle');
    settlePlayback(false);
  }, [cancelAutoplayQueue, setMessageAudioState, settlePlayback]);

  const playDescriptor = useCallback(async (descriptor) => {
    releaseAudio({ resetState: true });
    const requestId = audioRequestRef.current;
    const controller = typeof AbortController === 'undefined' ? null : new AbortController();
    audioAbortRef.current = controller;
    activeAudioRef.current = descriptor;
    setMessageAudioState(descriptor, 'loading');

    try {
      const blob = await speechApi.getMessageAudio(
        descriptor.mode,
        descriptor.sessionId,
        descriptor.messageId,
        controller?.signal,
      );
      if (audioAbortRef.current === controller) audioAbortRef.current = null;
      if (!mountedRef.current || requestId !== audioRequestRef.current) return false;

      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = audioRef.current || new Audio();
      audioRef.current = audio;
      audio.src = url;
      audio.preload = 'auto';

      const completion = new Promise(resolve => {
        playbackResolverRef.current = resolve;
      });
      audio.onplay = () => setMessageAudioState(descriptor, 'playing');
      audio.onpause = () => {
        if (activeAudioRef.current === descriptor && !audio.ended) {
          setMessageAudioState(descriptor, 'paused');
        }
      };
      audio.onended = () => {
        setMessageAudioState(descriptor, 'idle');
        activeAudioRef.current = null;
        if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
        settlePlayback(true);
      };
      audio.onerror = () => {
        if (activeAudioRef.current !== descriptor) return;
        releaseAudio({ resetState: false });
        setMessageAudioState(descriptor, 'error', '音频播放失败，请重试');
      };

      await audio.play();
      return completion;
    } catch (error) {
      if (audioAbortRef.current === controller) audioAbortRef.current = null;
      if (requestId === audioRequestRef.current) {
        releaseAudio({ resetState: false });
        setMessageAudioState(descriptor, 'error', error?.message || '语音生成失败，请重试');
      }
      return false;
    }
  }, [releaseAudio, setMessageAudioState, settlePlayback]);

  const processAutoplayQueue = useCallback(async () => {
    const generation = autoplayGenerationRef.current;
    if (autoplayRunningRef.current === generation) return;
    autoplayRunningRef.current = generation;
    try {
      while (
        generation === autoplayGenerationRef.current
        && autoplayQueueRef.current.length
      ) {
        const descriptor = autoplayQueueRef.current.shift();
        await playDescriptor(descriptor);
      }
    } finally {
      if (autoplayRunningRef.current === generation) {
        autoplayRunningRef.current = null;
      }
    }
  }, [playDescriptor]);

  const enqueueAutoplay = useCallback((messageIds, targetSessionId = sessionId, targetMode = mode) => {
    if (!targetSessionId || !targetMode) return;
    const ids = Array.isArray(messageIds) ? messageIds : [messageIds];
    ids.filter(id => id != null).forEach(messageId => {
      autoplayQueueRef.current.push({
        mode: targetMode,
        sessionId: targetSessionId,
        messageId,
      });
    });
    processAutoplayQueue();
  }, [mode, processAutoplayQueue, sessionId]);

  const toggleAudio = useCallback(async (
    messageId,
    targetSessionId = sessionId,
    targetMode = mode,
  ) => {
    if (!targetSessionId || !targetMode || messageId == null) return;
    const descriptor = { mode: targetMode, sessionId: targetSessionId, messageId };
    const active = activeAudioRef.current;
    const audio = audioRef.current;
    cancelAutoplayQueue();

    if (active && audioKey(active) === audioKey(descriptor) && audio) {
      if (!audio.paused) {
        audio.pause();
        return;
      }
      try {
        await audio.play();
      } catch (error) {
        releaseAudio({ resetState: false });
        setMessageAudioState(descriptor, 'error', error?.message || '音频播放失败，请重试');
      }
      return;
    }
    await playDescriptor(descriptor);
  }, [cancelAutoplayQueue, mode, playDescriptor, releaseAudio, sessionId, setMessageAudioState]);

  const retryAudio = useCallback((
    messageId,
    targetSessionId = sessionId,
    targetMode = mode,
  ) => {
    if (!targetSessionId || !targetMode || messageId == null) return;
    cancelAutoplayQueue();
    playDescriptor({ mode: targetMode, sessionId: targetSessionId, messageId });
  }, [cancelAutoplayQueue, mode, playDescriptor, sessionId]);

  const stopAudio = useCallback(() => {
    releaseAudio({ resetState: true, clearQueue: true });
  }, [releaseAudio]);

  const startRecording = useCallback(async () => {
    if (!sessionId || !mode) {
      setSpeechStatus('error');
      setSpeechError('当前会话尚未准备好');
      return;
    }
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setSpeechStatus('error');
      setSpeechError('当前浏览器不支持录音，请继续使用文字输入');
      return;
    }

    setSpeechError(null);
    const generation = recordingGenerationRef.current + 1;
    recordingGenerationRef.current = generation;
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current || generation !== recordingGenerationRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      const mimeType = MIME_CANDIDATES.find(type => MediaRecorder.isTypeSupported?.(type)) || '';
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recordingContextRef.current = { generation, mode, sessionId };
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      recordingChunksRef.current = [];

      recorder.ondataavailable = event => {
        if (event.data?.size) recordingChunksRef.current.push(event.data);
      };
      recorder.onerror = event => {
        stopMediaTracks();
        if (!mountedRef.current || generation !== recordingGenerationRef.current) return;
        setSpeechStatus('error');
        setSpeechError(recorderErrorMessage(event.error));
      };
      recorder.onstop = async () => {
        const chunks = recordingChunksRef.current;
        const context = recordingContextRef.current;
        mediaRecorderRef.current = null;
        recordingChunksRef.current = [];
        recordingContextRef.current = null;
        stopMediaTracks();
        if (!mountedRef.current || !context || context.generation !== recordingGenerationRef.current) return;

        const actualMime = recorder.mimeType || mimeType || chunks[0]?.type || 'audio/webm';
        const blob = new Blob(chunks, { type: actualMime });
        if (!blob.size) {
          setSpeechStatus('error');
          setSpeechError('未录到有效音频，请重试');
          return;
        }

        setSpeechStatus('transcribing');
        const controller = typeof AbortController === 'undefined' ? null : new AbortController();
        transcriptionAbortRef.current = controller;
        try {
          const uploadBlob = await convertToWav(blob).catch(() => blob);
          const file = new File(
            [uploadBlob],
            `recording.${fileExtension(uploadBlob.type || actualMime)}`,
            { type: uploadBlob.type || actualMime },
          );
          const result = await speechApi.transcribe(
            context.sessionId,
            context.mode,
            file,
            controller?.signal,
          );
          if (!mountedRef.current || context.generation !== recordingGenerationRef.current) return;
          const text = String(result?.text || '').trim();
          if (!text) throw new Error('未识别到有效文本，请重试');
          setSpeechStatus('idle');
          setSpeechError(null);
          onTranscriptionRef.current?.(text, result);
        } catch (error) {
          if (!mountedRef.current || context.generation !== recordingGenerationRef.current) return;
          setSpeechStatus('error');
          setSpeechError(error?.message || '语音转写失败，请重试');
        } finally {
          if (transcriptionAbortRef.current === controller) {
            transcriptionAbortRef.current = null;
          }
        }
      };

      recorder.start();
      setSpeechStatus('recording');
      recordingTimerRef.current = setTimeout(() => {
        if (recorder.state !== 'inactive') recorder.stop();
      }, MAX_RECORDING_MS);
    } catch (error) {
      if (!mountedRef.current || generation !== recordingGenerationRef.current) {
        stream?.getTracks().forEach(track => track.stop());
        return;
      }
      if (mediaStreamRef.current === stream) {
        stopMediaTracks();
      } else {
        stream?.getTracks().forEach(track => track.stop());
      }
      setSpeechStatus('error');
      setSpeechError(recorderErrorMessage(error));
    }
  }, [mode, sessionId, stopMediaTracks]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder?.state && recorder.state !== 'inactive') recorder.stop();
  }, []);

  const clearSpeechError = useCallback(() => {
    setSpeechError(null);
    setSpeechStatus(current => current === 'error' ? 'idle' : current);
  }, []);

  const getAudioState = useCallback((
    messageId,
    targetSessionId = sessionId,
    targetMode = mode,
  ) => {
    if (!targetSessionId || !targetMode || messageId == null) {
      return { status: 'idle', error: null };
    }
    return audioStates[audioKey({
      mode: targetMode,
      sessionId: targetSessionId,
      messageId,
    })]
      || { status: 'idle', error: null };
  }, [audioStates, mode, sessionId]);

  useEffect(() => {
    cancelRecording();
    stopAudio();
    setAudioStates({});
  }, [sessionId, mode, cancelRecording, stopAudio]);

  useEffect(() => {
    const handlePageHide = () => {
      cancelRecording();
      stopAudio();
    };
    window.addEventListener('pagehide', handlePageHide);
    return () => window.removeEventListener('pagehide', handlePageHide);
  }, [cancelRecording, stopAudio]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cancelRecording();
      stopAudio();
    };
  }, [cancelRecording, stopAudio]);

  return {
    speechStatus,
    speechError,
    isRecordingSupported: typeof MediaRecorder !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia),
    startRecording,
    stopRecording,
    cancelRecording,
    clearSpeechError,
    getAudioState,
    toggleAudio,
    retryAudio,
    enqueueAutoplay,
    stopAudio,
  };
}
