import { useRef, useState } from 'react';
import { Fingerprint, Image as ImageIcon, Link, Upload, X } from 'lucide-react';
import TagInput from './TagInput';
import { useDialog } from '../../context/DialogContext';
import { Button } from '@/components/ui/button';

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
      <div className="mb-4 flex items-center gap-2">
        <Fingerprint className="h-5 w-5 text-primary" aria-hidden="true" />
        <h3 className="font-archive-serif text-lg font-semibold text-foreground">身份信息 Identity</h3>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {infoFields.map(({ key, label, value, multiline }) => (
          <div key={key} className={multiline ? 'md:col-span-2' : ''}>
            <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">
              {label}
            </label>
            {multiline ? (
              <textarea
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                rows={3}
                className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-archive-serif text-base leading-7 text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            ) : (
              <input
                type="text"
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                className="min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-serif text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Aliases */}
      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">
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
        <label className="block font-archive-mono text-[11px] uppercase text-muted-foreground">
          头像 Avatar
        </label>

        <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-start">
          {/* Preview */}
          <div
            className={`relative h-24 w-24 flex-shrink-0 overflow-hidden rounded-md border-2 border-dashed ${
              dragOver ? 'border-primary bg-primary/5' : 'border-border'
            }`}
          >
            {avatarUrl && !imgError ? (
              <img
                src={avatarUrl}
                alt="Avatar"
                className="h-full w-full object-cover"
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center bg-muted/40">
                <ImageIcon className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex-1 space-y-2">
            <button
              type="button"
              className={`relative min-h-20 w-full cursor-pointer rounded-md border-2 border-dashed px-3 py-4 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                dragOver
                  ? 'border-primary bg-primary/5'
                  : 'border-border bg-muted/25 hover:bg-muted/40'
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              <Upload className="mx-auto mb-1 h-4 w-4 text-primary" aria-hidden="true" />
              <span className="block font-archive-mono text-[10px] text-muted-foreground">
                点击或拖放上传 (PNG/JPEG/WebP ≤2MB)
              </span>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              className="hidden"
              onChange={handleFileChange}
            />

            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <Link className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <input
                  type="text"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleUrlSubmit(); }}
                  placeholder="或粘贴网络图片 URL..."
                  className="min-h-11 w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 font-archive-mono text-xs text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={handleUrlSubmit}
                disabled={!urlInput.trim()}
              >
                设置
              </Button>
            </div>

            {avatarUrl && (
              <Button
                type="button"
                variant="ghost"
                onClick={handleClear}
                className="text-destructive hover:bg-destructive/5 hover:text-destructive"
              >
                <X aria-hidden="true" />
                清除头像
              </Button>
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
