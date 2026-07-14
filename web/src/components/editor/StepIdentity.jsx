import { useRef, useState } from 'react';
import { Contact, Upload, Link, X, Image as ImageIcon } from 'lucide-react';
import TagInput from './TagInput';
import { useDialog } from '../../context/DialogContext';

export default function StepIdentity({ formData, updateField, showAvatar = true }) {
  const dialog = useDialog();
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
      <div className="memoria-section-heading">
        <Contact size={18} />
        <h3 className="font-mono text-base font-bold text-zinc-100 sm:text-lg">身份信息 Identity</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {infoFields.map(({ key, label, value, multiline }) => (
          <div key={key} className={multiline ? 'md:col-span-2' : ''}>
            <label className="memoria-form-label">
              {label}
            </label>
            {multiline ? (
              <textarea
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                rows={3}
                className="memoria-form-control"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            ) : (
              <input
                type="text"
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                className="memoria-form-control"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Aliases */}
      <div>
        <label className="memoria-form-label">
          别名 Aliases
        </label>
        <TagInput
          tags={meta.aliases || []}
          onChange={(tags) => updateField('meta.aliases', tags)}
          placeholder="Add alias..."
        />
      </div>

      {/* Avatar */}
      {showAvatar && <div className="space-y-3">
        <label className="memoria-form-label">
          头像 Avatar
        </label>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-start gap-4">
          {/* Preview */}
          <div
            className={`relative h-24 w-24 flex-shrink-0 overflow-hidden rounded-lg border-2 border-dashed bg-black/25 ${
              dragOver ? 'border-cyber-green/60' : 'border-cyber-green/20'
            }`}
          >
            {avatarUrl && !imgError ? (
              <img
                src={avatarUrl}
                alt="Avatar"
                className="w-full h-full object-cover"
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <ImageIcon size={28} className="text-cyber-green/25" />
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex-1 space-y-2">
            <div
              className={`relative rounded border-2 border-dashed px-3 py-4 text-center cursor-pointer transition-colors ${
                dragOver
                  ? 'border-cyber-green/55 bg-cyber-green/[0.08]'
                  : 'border-cyber-green/20 bg-black/15 hover:border-cyber-green/40 hover:bg-cyber-green/[0.04]'
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              <Upload size={16} className="mx-auto mb-1 text-cyber-green/55" />
              <p className="text-[10px] font-mono text-cyber-green/45">
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
                <Link size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyber-green/35" />
                <input
                  type="text"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleUrlSubmit(); }}
                  placeholder="或粘贴网络图片 URL..."
                  className="memoria-form-control pl-8 text-xs"
                />
              </div>
              <button
                onClick={handleUrlSubmit}
                disabled={!urlInput.trim()}
                className="memoria-button px-3 disabled:opacity-30"
              >
                设置
              </button>
            </div>

            {avatarUrl && (
              <button
                onClick={handleClear}
                className="flex min-h-[44px] items-center gap-1 text-[10px] font-mono text-red-300/60 transition-colors hover:text-red-300"
              >
                <X size={10} />
                清除头像
              </button>
            )}
          </div>
        </div>
      </div>}
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
      dialog.alert({
        title: '头像文件过大',
        message: '请选择 2MB 以内的 PNG、JPEG、GIF 或 WebP 图片。',
        variant: 'warning',
      });
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
      dialog.alert({
        title: '头像链接不可用',
        message: '无法加载这张网络图片，请检查链接是否有效，或换一个可公开访问的图片地址。',
        variant: 'warning',
      });
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
