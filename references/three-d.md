# 2D × 3D：把 three.js 用进这支片子里

这份文件只解决一个问题：**什么时候该上 3D，以及 2D（DOM / Canvas / 文字）怎么和 3D 合成一个画面**。
编排本身的规则仍然在 [choreography.md](choreography.md)，这里只管 3D 这一层怎么接。

前置条件只有一条——工程里写 `"libs": ["three"]`：

```powershell
python vs.py libs --install three    # 只需要一次；装完随仓库走，渲染时完全不联网
```

```jsonc
{ "libs": ["three"], "scene": "scenes/take.html", "duration": 8 }
```

落盘的是 `assets/lib/three/three.iife.min.js`（约 750KB · MIT · r186）。它**不是官方产物**：three 从 r150
起只发 ESM，而这条流水线的注入路径（Playwright 的 init script）没有模块加载器。所以 vendor 时用 esbuild
把它打成单文件 IIFE，并在文件末尾用 footer 显式写 `window.THREE=THREE;`——因为 init script 是**当函数体执行**的，
裸 `var THREE` 只会变成函数里的局部变量，这一点踩过一次。

打包进去的除了核心，还有四个 addon：

| addon | 用途 |
| --- | --- |
| `CSS3DRenderer` / `CSS3DObject` / `CSS3DSprite` | 把**真实 DOM** 摆进 3D 空间（透视、倾斜、纵深） |
| `RoomEnvironment` + `PMREMGenerator` | 不用下载任何 HDR 文件就有一套棚拍环境光 |
| `EffectComposer` / `RenderPass` / `UnrealBloomPass` / `OutputPass` | 辉光，3D 看起来"像拍的"多半靠它 |

---

## 0. 先记住三件事

1. **WebGL 是软件渲染的**。headless Chromium 走 ANGLE + SwiftShader，能跑，但要按实测预算：
   1280×720 + 一个中等复杂度的模型 + bloom，实测约 **0.2 秒/帧**（105 帧、`jobs: 2`，端到端 21 秒）。
   分辨率是第一杠杆，bloom 是第二，面数是第三。别把 4K 和复杂几何体当默认。
2. **3D 也必须只按 `t` 求值**。不要 `renderer.setAnimationLoop()`、不要 `THREE.Clock`、不要 `OrbitControls`
   （那是交互件，不是渲染件）。所有旋转与位移都写成 `t` 的函数，然后在 `seek(t)` 末尾调一次 `view.render()`。
3. **同一个 `t` 必须得到同一帧**。实测：同一个 `t` 渲两次，PNG 的 sha256 完全一致（含 bloom）。
   一旦引入 `Date.now()`、`Math.random()` 或库自带的 ticker，这条立刻破。

---

## 1. 三个入口

```js
const view = Scene.three({ /* WebGL 图层 */ });
const css  = Scene.css3d({ /* CSS3D 图层：真 DOM 在 3D 里 */ });
const s    = Scene.surface(512, 320);   // 离屏 2D 画布，画完可以当贴图
```

`Scene.three(opts)` 返回：

| 字段 | 说明 |
| --- | --- |
| `renderer` / `scene` / `camera` | 原样给你，不封装 |
| `domElement` | 那个 `<canvas>`，已经绝对定位铺满 host |
| `size` | `{ w, h }`，CSS 像素 |
| `environment({sigma, background})` | RoomEnvironment → `scene.environment`，一行搞定棚拍光 |
| `bloom({strength, radius, threshold})` | 接上 EffectComposer；之后 `render()` 自动走 composer |
| `fit()` | 重新量 host 并同步尺寸（尺寸变了才调，不要每帧调） |
| `render()` | **放进 `seek(t)` 的那一下** |
| `dispose()` | 释放几何体/材质/renderer |

`opts`：`{ host, width, height, alpha=true, antialias=false, pixelRatio=1, background, css,
camera: { fov, position:[x,y,z], lookAt:[x,y,z], near, far } }`。
`pixelRatio` 默认锁 1，因为渲染器是按 CSS 像素截图的——让它变成 2 只会白花一倍时间。

`Scene.css3d(opts)` 返回 `renderer` / `scene` / `camera` / `domElement` / `size` /
`object(el, {position, rotation(度), scale})` / `fit()` / `render()`。

---

## 2. 四种组合方式，各自什么时候用

### A. 3D 在下面，DOM 文字在上面（默认选择）

最稳的一种：3D 负责空间与质感，文字仍是真 DOM，永远锐利、永远不受贴图分辨率限制。

```js
const S = Scene.mount({ background: "#080a0b" });

const glLayer = S.layer("gl");
const view = Scene.three({ host: glLayer, background: "#080a0b" });
view.scene.add(knot);
view.environment();
view.bloom({ strength: 0.5, radius: 0.45, threshold: 0.9 });

const uiLayer = S.layer("ui");           // 后建 = 在上面
const head = Scene.type(document.createElement("div"), 0.05, { weight: "600" });
head.textContent = "标题";
uiLayer.appendChild(head);

window.seek = (t) => {
  knot.rotation.y = t * 0.55;           // 3D 按 t 求值
  view.render();                         // 只在这里渲一次
};
```

要点：3D 用 `alpha: true`（默认）时 DOM 背景能透出来；想让 3D 完全接管底色就传 `background`。
**别**把文字画进 canvas 再当贴图（那就是 B 或 C，除非你确实要透视）。

### B. CSS3D：真 DOM 放进 3D 空间

适合"一块界面/卡片斜着飘在空间里"这种镜头。它渲染的是真 DOM，所以文字清晰、CSS 阴影和圆角都还在。

```js
const cssLayer = S.layer("css3d");
const css = Scene.css3d({ host: cssLayer, camera: { fov: 40, position: [0, 0, 900] } });

const card = document.createElement("div");
card.className = "css3d-card";
card.innerHTML = "<b>CSS3D</b>真 DOM，斜放在 3D 空间里";
const obj = css.object(card, { position: [-330, -120, 260], rotation: [0, 26, 0] });

window.seek = (t) => {
  obj.rotation.y = (26 - 14 * Math.min(1, t / 3)) * Math.PI / 180;
  css.render();
};
```

两个必须知道的限制：

- **CSS3D 和 WebGL 不能逐个物体交错**。CSS3D 的 DOM 层是整层压在上面（或下面）的。要么 3D 全在它后面，
  要么它全在 3D 后面。需要"半个卡片插进 3D 物体里"，用 A + C 的组合，别指望 CSS3D。
- CSS3D 用的是 `px` 尺度的相机（`position: [0,0,800]` 那种），跟 WebGL 那套米制坐标不是一回事。
  两套相机要各自调参，别想着共用一个。

### C. Canvas2D → 贴图：把 2D 画的东西放到 3D 表面上

图表、示意图形、带排版的文字块，都可以先用 Canvas2D 画好，再贴到 plane / 曲面 / 物体上。
好处是**完全可控、无外部资源、无网络**。

```js
const s = Scene.surface(512, 320);
s.ctx.fillStyle = "#0e1414"; s.ctx.fillRect(0, 0, 512, 320);
s.ctx.fillStyle = "#e0455f"; s.ctx.fillRect(40, 46, 64, 6);
s.ctx.fillStyle = "#eef2f0";
s.ctx.font = "600 46px 'Microsoft YaHei', system-ui, sans-serif";
s.ctx.fillText("2D 贴图", 40, 140);

const tex = new THREE.CanvasTexture(s.canvas);
tex.colorSpace = THREE.SRGBColorSpace;          // 不设会偏灰
const plate = new THREE.Mesh(new THREE.PlaneGeometry(1.55, 0.97),
                             new THREE.MeshBasicMaterial({ map: tex }));
view.scene.add(plate);
```

- 用 `MeshBasicMaterial` 贴"本来就是成品"的 2D 图，颜色不被光照二次改变；
  想让面板参与光照（接受阴影、被 bloom 打到）就用 `MeshStandardMaterial`。
- 贴图尺寸按实际显示像素给：一个占画面 30% 宽的平面在 1280 宽的成片里约 380px，
  给 512 宽足够；给 4096 只会让软件渲染更慢。
- 改完 canvas 内容要 `tex.needsUpdate = true`（每帧重画才需要，静态图不用）。

### D. bloom 只作用于 3D，DOM 层保持锐利

因为 bloom 是在 3D 的 composer 里做的，DOM 图层天然不受影响——这正是"3D 有光、文字还清楚"的原因。
反过来，如果你想要"整屏都有辉光"，那只能在**最上面加一个 DOM 图层**做近似（径向渐变 + `screen` 混合），
不要试图把 DOM 塞进 composer。

```js
const wash = document.createElement("div");
wash.style.cssText =
  "position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;" +
  "background:radial-gradient(circle at 26% 74%, rgba(56,189,248,.20) 0%, rgba(56,189,248,0) 55%)";
uiLayer.appendChild(wash);
```

### E. 让 2D 和 3D 像"同一个空间"的四个手法

分开做容易露馅。这几件事做了，两层就会咬合：

1. **共享运动**：DOM 元素的位移方向和 3D 相机推拉一致。相机往里推，DOM 也轻微放大或上移
   （用同一个 `ease`，幅度差 3-5 倍）。
2. **共享光向**：3D 的光从左上来，DOM 的渐变高光就放左上；阴影方向别跟 3D 打架。
3. **共享色彩**：DOM 的强调色取自同一套调色（`Scene`/`style` 里的 accent），3D 材质的 `color` 用同一个值，
   中间用雾（`scene.fog`）或暗角把两侧压到一起。
4. **共享颗粒**：在所有图层之上再放一层极淡的噪点/扫描线（`Kit.texture` 里的那几种），
   2D 和 3D 就被"同一台相机拍下来"了。

---

## 3. 镜头与光照的最小可用配置

```js
view.environment();                              // 一行 = 棚拍环境光，不需要 HDR 文件
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(2.5, 3.2, 2.0);
view.scene.add(key);                             // 需要明确方向感时再加主光

view.camera.position.set(0, 0.5, 5.4);           // 相机也只按 t 动
view.camera.lookAt(0, 0, 0);

// 想加纵深就加雾，颜色取背景色，DOM 层不会被它影响
view.scene.fog = new THREE.Fog("#080a0b", 6, 16);
```

- 相机运动写成 `t` 的纯函数：`view.camera.position.z = 5.4 - 0.7 * ease(t / 3.2)`，然后 `lookAt`。
- 不要用 `OrbitControls`：它读鼠标、带自己的阻尼状态，既不可 seek 也没有必要。
- 想要"手持感"：在相机位置上叠 `Math.sin(t * 1.7) * 0.02` 这种确定性抖动。

---

## 4. 性能与预算（本机实测）

| 场景 | 每帧 | 备注 |
| --- | --- | --- |
| DOM / SVG / Canvas2D 图层 | ~0.2s | 这就是原来 2D 流水线的基线 |
| + WebGL 中等模型 + environment | 略高于基线 | 一个 TorusKnot（148×24 段）实测整片 105 帧 21 秒 |
| + bloom（`EffectComposer`） | 再慢一档 | 多趟半分辨率模糊；要省就先关它 |

省时间的顺序：**先降分辨率**（1280×720 → 960×540，像素数少 44%）→ **关 bloom** → **减面数/减尺寸** →
把静止区间写进 `hold`。`vs.py plan` 会给出这个工程的帧数与预估时间，先看它再决定。

---

## 5. 禁忌清单

- **不要 `setAnimationLoop` / `requestAnimationFrame` / `THREE.Clock`**：帧不再由 `t` 决定，缓存与验收全部失效。
- **不要 `OrbitControls` / `PointerLockControls`**：交互件，渲染端没有输入。
- **不要用 `GLTFLoader` 读外部文件**：`file://` 下 XHR 被拦，模型加载不进来。
  要 3D 资产就走"几何体 + 材质现场搭"或把数据内联进场景文件。
- **不要把 DOM 逐元素插进 WebGL 的深度里**：做不到，CSS3D 是整层合成的。
- **不要在 `seek(t)` 里 `new` 几何体或材质**：那会每帧泄漏一份 GPU 资源。几何体、材质、贴图都只建一次，
  每帧只改它们的数值。
- **不要在 3D 层上再套一层"网页感"的圆角卡片 + 蓝紫渐变**：那是 AI 味清单里的头两条，
  3D 只是把同样的套路渲得更慢。

---

## 6. 交付前检查

- [ ] 同一个 `t` 渲两次，帧完全一致（`vs.py preview --at X` 两次，比 sha256）
- [ ] `node --check` 通过；场景里搜不到 `setAnimationLoop` / `Clock` / `Date.now`
- [ ] `vs.py run` 的 `content` 与 `motion` 都过（3D 层黑掉时 `content` 会抓出来）
- [ ] DOM 文字没有被 3D 层压住或截断，安全区内
- [ ] 关掉动效看一眼静帧：这一帧本身站得住吗（[choreography.md](choreography.md) §8.1）
- [ ] 成本对得上：`vs.py plan` 的预计时间在你可接受的范围内
