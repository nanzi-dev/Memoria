# 项目需求：Memoria 角色卡编辑器网页

请基于以下需求实现一个完整的前端网页项目（React + Vite），包含首页和添加角色页面两个核心页面。

## 一、技术栈要求

- React + Vite
- Three.js / @react-three/fiber / @react-three/drei（用于 3D 工牌挂绳效果）
- 需要用到的依赖库：`@react-three/fiber`、`@react-three/drei`、`@react-three/rapier`（物理引擎，Lanyard 组件需要）、`meshline`
- 状态管理可用 React Context 或简单的 useState 提升即可，无需引入额外状态库
- 数据先做本地持久化（localStorage），暂不需要后端

## 二、整体风格

- 暗色科技/赛博朋克风格，标题使用故障文字效果，背景使用故障终端效果，整体视觉统一
- 页面主色调可参考：背景深黑 `#0b0b0c` / `#120F17`，点缀荧光绿 `#A7EF9E`

## 三、首页（Home）

### 3.1 标题
页面顶部标题文字为 **"Memoria"**，需要使用故障文字组件 `GlitchText`（完整源码见下方"组件源码"部分，直接集成，不要用其他实现替代）。

调用示例：
```jsx
<GlitchText speed={1} enableShadows={true} enableOnHover={false} className="home-title">
  Memoria
</GlitchText>
```

### 3.2 背景
首页背景使用 `FaultyTerminal` 组件（完整源码见下方，需要自行安装依赖 `ogl` 或按需实现其 WebGL/Canvas 效果，若源码中依赖了某个 npm 包请一并安装）。

调用示例：
```jsx
<FaultyTerminal
  scale={1.5}
  gridMul={[2, 1]}
  digitSize={1.2}
  timeScale={0.5}
  pause={false}
  scanlineIntensity={0.5}
  glitchAmount={1}
  flickerAmount={1}
  noiseAmp={1}
  chromaticAberration={0}
  dither={0}
  curvature={0.1}
  tint="#A7EF9E"
  mouseReact
  mouseStrength={0.5}
  pageLoadAnimation
  brightness={0.6}
/>
```
作为首页的全屏固定背景层（`position: fixed`，`z-index` 置于内容之下）。

### 3.3 角色工牌展示
- 首页主体区域以网格/列表形式展示所有已创建的角色，每个角色显示为一张 **3D 工牌**，使用 `Lanyard` 组件（完整源码见下方）实现悬挂/物理摆动的挂绳工牌效果。
- 每张工牌的正面（frontImage）显示该角色的头像/立绘，背面（backImage）可显示角色的关键信息卡片图（例如姓名、职位等，可用 canvas 动态生成图片或使用默认背景+叠加 DOM 文本）。
- 调用示例：
```jsx
<Lanyard
  position={[0, 0, 20]}
  gravity={[0, -40, 0]}
  frontImage={character.avatarUrl}
  backImage={character.cardBackUrl}
  imageFit="cover"
/>
```
- 多个角色需要在网格中平铺展示，每个角色对应一个独立的 `Lanyard` 3D 场景卡片（可用固定宽高的容器分别渲染，避免多个 Canvas 性能问题时可考虑虚拟化或懒加载，但先实现基础功能即可）。
- 每张工牌下方或悬浮时显示角色姓名。
- 点击某个工牌可进入"角色详情/编辑"视图（复用添加角色页面的表单结构，预填充数据，可编辑保存）。

### 3.4 添加角色入口
首页需要有一个明显的"添加角色"按钮/入口（例如一张空白/虚线边框的占位工牌，或右下角悬浮按钮），点击后跳转到"添加角色"页面。

## 四、添加角色页面（Add Character）—— 严格按参考图还原

已提供一张设计参考图（牛皮纸档案夹 + 机密档案卡），请**尽量像素级还原其版式结构与视觉细节**，配色可整体调深（呼应首页暗色科技风格），但**布局、模块、栏位必须与参考图一致**，不要自由发挥版式。

### 4.1 整体结构：牛皮纸文件夹 + 夹纸档案卡

- 最外层是一个**牛皮纸色文件夹**（folder）背景，顶部左侧有一个凸起的文件夹标签角（folder tab），标签角上印着：
  - 一行居中文字："★ 角色档案 ★"（两侧红色小五角星）
  - 下方小字副标题："CHARACTER FILE"
- 文件夹整体带轻微纸张纹理/做旧质感（可用 CSS noise 纹理或轻微阴影模拟，不必是真实位图纹理，用渐变+box-shadow 模拟卡纸质感即可）
- 文件夹右侧边缘露出"夹着更多纸张"的层叠效果（用 2-3 层轻微错位、旋转的矩形模拟纸堆厚度）
- 档案卡右侧夹着一个**金属长尾夹/文件夹夹子（clipboard clip）**图形，用 CSS/SVG 画一个银色金属夹子造型，固定在卡片右侧偏上位置，增强"档案被夹住"的真实感

### 4.2 档案卡（表单主体）

档案卡是浮在文件夹上方的一张米白色纸张，圆角矩形，带阴影，内部从上到下依次为：

**a. 卡头**
- 左侧大标题："角色简历 / 档案卡"，下方小字副标题："CHARACTER RESUME / PROFILE CARD"
- 右上角一个装饰性图形：类似指南针/邮戳的圆形图案 + 波浪线（可用简单 SVG 绘制一个八角星罗盘图案），纯装饰，不需要交互

**b. 头像区（左）+ 基础信息表（右），左右两栏布局**
- 左侧：一张"照片"样式的头像上传区域，模拟拍立得/回形针别住的照片效果：
  - 白色相框边框，头像图片居中显示（点击/拖拽上传角色头像，用于后续生成 Lanyard 工牌的 frontImage）
  - 相框左上角画一个回形针（paperclip）图形，叠加在相框边缘，做出"别在档案上"的效果
  - 相框下方是一个可编辑的"角色台词/座右铭"文本框，样式为手写引号文字，例如："我从不选择命运，我只定义规则，"（用户可自定义输入这句话，留空则不显示）
- 右侧：基础信息表，逐行显示"标签：输入框"，每行之间用浅色横线分隔，字段依次为：
  1. 姓名
  2. 性别
  3. 年龄
  4. 身高
  5. 职业
  6. 所属组织
  7. 身份编号
  8. 出生日期
  9. 出生地
  - 每个字段左侧是灰色标签文字，右侧是可编辑的输入框（未编辑时显示为纯文本样式，聚焦/点击时切换为输入框，或者直接使用带底部细线的 input，无边框、无背景，融入纸张观感）

**c. 角色概述 + 性格特征，左右两栏**
- 左栏标题："👤 角色概述"，下方是一个多行文本框（自动增高），用于填写角色背景简述
- 右栏标题："👤 性格特征"，下方是**标签云**形式：多个圆角矩形小标签（灰底黑字，如"冷静理智""洞察力强""极度自律"），支持动态增删标签（输入后回车新增一个标签，点击标签上的×可删除）

**d. 技能专长 + 经历概要，左右两栏**
- 左栏标题："🎯 技能专长"：多行"技能名 + 进度条"列表，例如"情报分析 ▓▓▓▓▓▓▓▓░░"。进度条为深色填充、浅灰底色的横向条形，用户可编辑技能名称和拖动/输入调整百分比（0-100）。支持增删行。
- 右栏标题："📋 经历概要"：时间轴列表，每行格式为"年份　事件描述"，例如"2015年　加入黑曜特别行动组"。支持增删行，年份和描述均可编辑。

**e. 卡片底部**
- 左下角显示两个只读/自动生成的元信息："档案状态：机密"（可做成下拉选择：机密/绝密/公开等），"最后更新：{自动填充为最后一次保存的日期}"
- 右下角是一个旋转倾斜的红色印章图形，文字为"机密档案 / CONFIDENTIAL"，用 CSS border + rotate 模拟盖章效果（半透明红色边框圆角矩形，文字红色，整体旋转 -8deg 左右，边框做成双线或粗糙描边模拟印章质感）

### 4.3 交互与动效

- 进入添加角色页面时，档案卡有一个从下方滑入 + 轻微旋转回正的入场动画（模拟"抽出档案"的动作）
- 头像上传：点击照片区域触发文件选择，选中后实时预览
- 标签、技能、经历三处列表均支持"增加一项 / 删除某项"的按钮（用简洁的 + / × 小图标即可）
- 底部提供"保存"和"取消"按钮（可放在文件夹外部下方，或档案卡内部底部，样式与整体牛皮纸风格保持一致，例如做成"盖章确认"式按钮），保存后返回首页，在工牌墙中新增或更新该角色的 Lanyard 工牌
- 整体色调可比参考图略深一档（例如牛皮纸色替换为深棕/暗灰棕），文字保持深色以保证可读性，避免与首页的暗色科技风完全割裂，但**不要**改成赛博朋克荧光配色——此页面应保持"纸质档案"的怀旧质感，作为与首页科技感的一种反差设计

## 五、数据结构建议

```js
{
  id: string,
  avatarUrl: string,      // 头像，用于 Lanyard frontImage（对应参考图左侧拍立得照片）
  cardBackUrl: string,    // 卡片背面（可选，无则用默认背景+文字叠层）
  quote: string,          // 座右铭/台词，照片下方手写体文字
  name: string,           // 姓名
  gender: string,         // 性别
  age: string,            // 年龄
  height: string,         // 身高
  occupation: string,     // 职业
  organization: string,   // 所属组织
  idNumber: string,       // 身份编号
  birthDate: string,      // 出生日期
  birthPlace: string,     // 出生地
  overview: string,       // 角色概述（多行文本）
  personalityTags: string[], // 性格特征标签数组
  skills: [{ name: string, level: number }],   // 技能专长，level 为 0-100 进度
  timeline: [{ year: string, event: string }], // 经历概要
  fileStatus: string,     // 档案状态：机密 / 绝密 / 公开
  updatedAt: number,      // 最后更新时间戳
  createdAt: number
}
```

角色数据保存在 localStorage，key 建议为 `memoria-characters`，为数组结构。

## 六、页面结构建议

```
src/
  components/
    GlitchText.jsx
    GlitchText.css
    Lanyard.jsx
    Lanyard.css (如有)
    FaultyTerminal.jsx
    CharacterBadge.jsx      // 单个工牌容器，内部使用 Lanyard
    CharacterFolder.jsx     // 添加/编辑角色的文件夹表单
  pages/
    Home.jsx
    AddCharacter.jsx
  assets/
    card.glb
    lanyard.png
  App.jsx
  main.jsx
```

## 七、组件源码（请直接使用，不要重新实现）

### 7.1 GlitchText

`GlitchText.jsx`:
```jsx
import './GlitchText.css';

const GlitchText = ({ children, speed = 1, enableShadows = true, enableOnHover = true, className = '' }) => {
  const inlineStyles = {
    '--after-duration': `${speed * 3}s`,
    '--before-duration': `${speed * 2}s`,
    '--after-shadow': enableShadows ? '-5px 0 red' : 'none',
    '--before-shadow': enableShadows ? '5px 0 cyan' : 'none'
  };

  const hoverClass = enableOnHover ? 'enable-on-hover' : '';

  return (
    <div className={`glitch ${hoverClass} ${className}`} style={inlineStyles} data-text={children}>
      {children}
    </div>
  );
};

export default GlitchText;
```

`GlitchText.css`:
```css
.glitch {
  color: #fff;
  font-size: clamp(2rem, 10vw, 8rem);
  white-space: nowrap;
  font-weight: 900;
  position: relative;
  margin: 0 auto;
  user-select: none;
  cursor: pointer;
}

.glitch::after,
.glitch::before {
  content: attr(data-text);
  position: absolute;
  top: 0;
  color: #fff;
  background-color: #120F17;
  overflow: hidden;
  clip-path: inset(0 0 0 0);
}

.glitch:not(.enable-on-hover)::after {
  left: 10px;
  text-shadow: var(--after-shadow, -10px 0 red);
  animation: animate-glitch var(--after-duration, 3s) infinite linear alternate-reverse;
}
.glitch:not(.enable-on-hover)::before {
  left: -10px;
  text-shadow: var(--before-shadow, 10px 0 cyan);
  animation: animate-glitch var(--before-duration, 2s) infinite linear alternate-reverse;
}

.glitch.enable-on-hover::after,
.glitch.enable-on-hover::before {
  content: '';
  opacity: 0;
  animation: none;
}

.glitch.enable-on-hover:hover::after {
  content: attr(data-text);
  opacity: 1;
  left: 10px;
  text-shadow: var(--after-shadow, -10px 0 red);
  animation: animate-glitch var(--after-duration, 3s) infinite linear alternate-reverse;
}
.glitch.enable-on-hover:hover::before {
  content: attr(data-text);
  opacity: 1;
  left: -10px;
  text-shadow: var(--before-shadow, 10px 0 cyan);
  animation: animate-glitch var(--before-duration, 2s) infinite linear alternate-reverse;
}

@keyframes animate-glitch {
  0% { clip-path: inset(20% 0 50% 0); }
  5% { clip-path: inset(10% 0 60% 0); }
  10% { clip-path: inset(15% 0 55% 0); }
  15% { clip-path: inset(25% 0 35% 0); }
  20% { clip-path: inset(30% 0 40% 0); }
  25% { clip-path: inset(40% 0 20% 0); }
  30% { clip-path: inset(10% 0 60% 0); }
  35% { clip-path: inset(15% 0 55% 0); }
  40% { clip-path: inset(25% 0 35% 0); }
  45% { clip-path: inset(30% 0 40% 0); }
  50% { clip-path: inset(20% 0 50% 0); }
  55% { clip-path: inset(10% 0 60% 0); }
  60% { clip-path: inset(15% 0 55% 0); }
  65% { clip-path: inset(25% 0 35% 0); }
  70% { clip-path: inset(30% 0 40% 0); }
  75% { clip-path: inset(40% 0 20% 0); }
  80% { clip-path: inset(20% 0 50% 0); }
  85% { clip-path: inset(10% 0 60% 0); }
  90% { clip-path: inset(15% 0 55% 0); }
  95% { clip-path: inset(25% 0 35% 0); }
  100% { clip-path: inset(30% 0 40% 0); }
}
```

### 7.2 Lanyard（3D 挂绳工牌）

请从 React Bits 官方仓库获取 `Lanyard` 组件的完整源码（包含 `Lanyard.jsx` 与其依赖的 `card.glb`、`lanyard.png` 资源文件，位于仓库 `src/assets/lanyard` 目录下），并按以下方式集成：

调用方式：
```jsx
import Lanyard from './Lanyard'

<Lanyard
  position={[0, 0, 20]}
  gravity={[0, -40, 0]}
  frontImage={character.avatarUrl}
  backImage={character.cardBackUrl}
  imageFit="cover"
/>
```

集成要求：
1. 安装依赖：`@react-three/fiber`、`@react-three/drei`、`@react-three/rapier`、`meshline`
2. 将 `card.glb` 和 `lanyard.png` 放入 `src/assets/lanyard` 目录并在组件中导入
3. `frontImage` / `backImage` 用于运行时替换卡片正反面贴图为角色头像/信息卡
4. Vite 配置需添加：
```js
// vite.config.js
export default {
  assetsInclude: ['**/*.glb']
}
```
5. 每个角色的工牌应作为独立的小型 3D 场景渲染在网格布局的卡片容器中（例如每个容器固定 `width: 220px; height: 320px`），避免相互干扰。

### 7.3 FaultyTerminal（故障终端背景）

请从 React Bits 官方仓库获取 `FaultyTerminal` 组件完整源码并集成（该组件通常基于 WebGL/`ogl` 实现网格数字故障效果），调用方式：

```jsx
import FaultyTerminal from './FaultyTerminal';

<div style={{ width: '100%', height: '100vh', position: 'fixed', inset: 0, zIndex: -1 }}>
  <FaultyTerminal
    scale={1.5}
    gridMul={[2, 1]}
    digitSize={1.2}
    timeScale={0.5}
    pause={false}
    scanlineIntensity={0.5}
    glitchAmount={1}
    flickerAmount={1}
    noiseAmp={1}
    chromaticAberration={0}
    dither={0}
    curvature={0.1}
    tint="#A7EF9E"
    mouseReact
    mouseStrength={0.5}
    pageLoadAnimation
    brightness={0.6}
  />
</div>
```
若组件依赖 `ogl` 包，请一并 `npm install ogl`。

> 注：以上三个组件均来自开源组件库 **React Bits**（reactbits.dev），请从其官方 GitHub 仓库拉取对应组件的最新完整源码（含 CSS/资源文件），确保效果与示例一致。

## 八、交付要求

1. 项目可通过 `npm install && npm run dev` 直接运行
2. 首页能正常展示 Memoria 故障标题、故障终端背景、以及至少一个默认/示例角色工牌
3. 点击"添加角色"能打开文件夹表单页面，填写后保存能在首页新增对应工牌，数据刷新页面后仍保留（localStorage）
4. 点击已有工牌可进入编辑态，修改后可保存或删除
5. 代码结构清晰，组件拆分合理，附带简要 README 说明启动方式