import { useRef, useState } from 'react';
import { Upload, Link, X, Image as ImageIcon } from 'lucide-react';
import TagInput from './TagInput';

export default function StepIdentity({ formData, updateField }) {
  const meta = formData.meta || {};
  const identity = formData.identity || {};
  const avatarUrl = formData.avatar_url || null;
  const [dragOver, setDragOver] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [imgError, setImgError] = useState(false);
  const fileInputRef = useRef(null);

  const infoFields = [
    { key: 'meta.name', label: '姓名 Name', value: meta.name || '' },
    { key: 'meta.display_name', label: '显示名 Display Name', value: meta.display_name || '' },
    { key: 'identity.gender', label: '性别 Gender', value: identity.gender || '' },
    { key: 'identity.age', label: '年龄 Age', value: identity.age || '' },
    { key: 'identity.occupation', label: '职业 Occupation', value: identity.occupation || '' },
    { key: 'identity.race_or_species', label: '种族 Race/Species', value: identity.race_or_species || '' },
    { key: 'identity.social_status', label: '社会地位 Social Status', value: identity.social_status || '' },
    { key: 'identity.appearance', label: '外貌 Appearance', value: identity.appearance || '', multiline: true },
    { key: 'identity.core_identity_summary', label: '身份总结 Identity Summary', value: identity.core_identity_summary || '', multiline: true },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg text-cyber-ink/60">👤</span>
        <h3 className="font-mono text-lg font-bold text-cyber-ink">身份信息 Identity</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {infoFields.map(({ key, label, value, multiline }) => (
          <div key={key} className={multiline ? 'md:col-span-2' : ''}>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              {label}
            </label>
            {multiline ? (
              <textarea
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                rows={3}
                className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-amber-50/50 border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50 rounded-t resize-none transition-colors"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            ) : (
              <input
                type="text"
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Aliases */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          别名 Aliases
        </label>
        <TagInput
          tags={meta.aliases || []}
          onChange={(tags) => updateField('meta.aliases', tags)}
          placeholder="Add alias..."
        />
      </div>

      {/* Avatar */}
      <div className="space-y-3">
        <label className="block text-[11px] text-amber-700/60 font-mono uppercase tracking-wider">
          头像 Avatar
        </label>

        <div className="flex items-start gap-4">
          {/* Preview */}
          <div
            className="relative w-24 h-24 flex-shrink-0 rounded-lg overflow-hidden border-2 border-dashed"
            style={{ borderColor: dragOver ? '#D4A574' : '#C4B594' }}
          >
            {avatarUrl && !imgError ? (
              <img
                src={avatarUrl}
                alt="Avatar"
                className="w-full h-full object-cover"
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center bg-amber-100/30">
                <ImageIcon size={28} className="text-amber-700/30" />
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex-1 space-y-2">
            <div
              className={`relative rounded border-2 border-dashed px-3 py-4 text-center cursor-pointer transition-colors ${
                dragOver
                  ? 'border-amber-500 bg-amber-100/50'
                  : 'border-amber-300/40 hover:border-amber-400/60 bg-amber-50/30'
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              <Upload size={16} className="mx-auto text-amber-600/50 mb-1" />
              <p className="text-[10px] font-mono text-amber-700/50">
                点击或拖放上传 (PNG/JPEG/WebP ≤2MB)
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>

            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Link size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-amber-700/40" />
                <input
                  type="text"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleUrlSubmit(); }}
                  placeholder="或粘贴网络图片 URL..."
                  className="w-full pl-7 pr-2 py-1 text-xs font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none transition-colors"
                />
              </div>
              <button
                onClick={handleUrlSubmit}
                disabled={!urlInput.trim()}
                className="px-2 py-1 text-[10px] font-mono text-amber-700/60 hover:text-amber-800 border border-amber-300/30 rounded hover:bg-amber-100/50 disabled:opacity-30 transition-colors"
              >
                设置
              </button>
            </div>

            {avatarUrl && (
              <button
                onClick={handleClear}
                className="flex items-center gap-1 text-[10px] font-mono text-red-600/60 hover:text-red-700 transition-colors"
              >
                <X size={10} />
                清除头像
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }

  function handleFileChange(e) {
    const file = e.target.files[0];
    if (file) uploadFile(file);
  }

  function uploadFile(file) {
    if (!file.type.startsWith('image/')) return;
    if (file.size > 2 * 1024 * 1024) {
      alert('文件过大，最大 2MB');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      updateField('avatar_url', reader.result);
      setImgError(false);
      setUrlInput('');
    };
    reader.readAsDataURL(file);
  }

  function handleUrlSubmit() {
    const url = urlInput.trim();
    if (!url) return;
    // 用 Image 对象测试 URL 是否可加载
    setImgError(false);
    const img = new Image();
    img.onload = () => {
      updateField('avatar_url', url);
      setImgError(false);
    };
    img.onerror = () => {
      alert('头像 URL 不可用，请检查链接是否有效');
      setImgError(true);
    };
    img.src = url;
    setUrlInput('');
  }

  function handleClear() {
    updateField('avatar_url', null);
    setImgError(false);
    setUrlInput('');
  }
}
