/* three-kit.js - WebGL and CSS3D views for a scene, and nothing that runs on its own clock.
 *
 * These helpers do not hide three: you still build the geometry, the materials and the camera
 * moves. They remove the four things that are easy to get wrong inside a frame-exact renderer:
 *
 *   Scene.three(opts)   -> { renderer, scene, camera, environment(), bloom(), fit(), render() }
 *   Scene.css3d(opts)   -> { renderer, scene, camera, object(el), fit(), render() }
 *   Scene.surface(w,h)  -> an offscreen 2D canvas, ready to become a THREE.CanvasTexture
 *
 * The rule that matters: every helper is created once, with no animation loop, and `render()` is
 * called from inside `window.seek(t)`. Nothing here reads a clock, so the same t gives the same
 * frame - which is what makes a WebGL layer usable in this pipeline at all.
 *
 * Combining 2D and 3D, in short (full recipes: references/three-d.md):
 *   - 3D underneath, real HTML text above        two layers, `Scene.three` + `Scene.type`
 *   - HTML placed *inside* the 3D scene           `Scene.css3d` (real DOM, perspective transforms)
 *   - 2D drawing used as a texture                `Scene.surface` + `THREE.CanvasTexture`
 *   - bloom on the 3D layer only                  `view.bloom()` before you add DOM on top
 */
(function (global) {
  function lib() {
    if (!global.THREE) {
      throw new Error('3D helpers need the vendored three.js build: add "libs": ["three"] to project.json, then run: python vs.py libs --install three');
    }
    return global.THREE;
  }

  function hostOf(host) {
    return host || document.getElementById("stage") || document.body;
  }

  function sizeOf(host, o) {
    if (o.width && o.height) return { w: Math.round(o.width), h: Math.round(o.height) };
    const el = hostOf(host);
    return {
      w: Math.max(1, el.clientWidth || global.innerWidth),
      h: Math.max(1, el.clientHeight || global.innerHeight)
    };
  }

  /* Offscreen 2D canvas: draw with the plain Canvas2D API, then wrap it in a THREE.CanvasTexture.
   * The canvas is a normal DOM node, so text, paths, gradients and images all work. */
  function surface(w, h) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w));
    canvas.height = Math.max(1, Math.round(h));
    return { canvas, ctx: canvas.getContext("2d"), width: canvas.width, height: canvas.height };
  }

  function cameraFrom(T, cam, aspect) {
    const c = cam || {};
    const camera = new T.PerspectiveCamera(c.fov || 40, aspect, c.near || 0.1, c.far || 100);
    const p = c.position || [0, 0, 5];
    camera.position.set(p[0], p[1], p[2]);
    const look = c.lookAt || [0, 0, 0];
    camera.lookAt(look[0], look[1], look[2]);
    return camera;
  }

  /* A WebGL view: canvas, scene, camera, and one call you make from seek(t). */
  function view(opts) {
    const T = lib();
    const o = opts || {};
    const host = hostOf(o.host);
    const size = sizeOf(o.host, o);
    const renderer = new T.WebGLRenderer({
      alpha: o.alpha !== false,
      antialias: !!o.antialias,
      powerPreference: "high-performance"
    });
    // Pixel ratio is pinned to 1 on purpose: the renderer screenshots at CSS pixel size, so an
    // accidental 2x backing store would only cost time and change the frame.
    renderer.setPixelRatio(o.pixelRatio || 1);
    renderer.setSize(size.w, size.h, false);
    renderer.domElement.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;display:block;" + (o.css || "");
    host.appendChild(renderer.domElement);

    const scene = new T.Scene();
    if (o.background) scene.background = new T.Color(o.background);
    const camera = cameraFrom(T, o.camera, size.w / size.h);

    let composer = null;
    let disposed = false;

    const api = {
      THREE: T, renderer, scene, camera, size,
      domElement: renderer.domElement,

      /* Studio lighting with no external HDR file: RoomEnvironment through PMREMGenerator. */
      environment(e) {
        const opt = e || {};
        const pmrem = new T.PMREMGenerator(renderer);
        const env = pmrem.fromScene(new T.RoomEnvironment(), opt.sigma === undefined ? 0.04 : opt.sigma);
        scene.environment = env.texture;
        if (opt.background) scene.background = env.texture;
        pmrem.dispose();
        return api;
      },

      /* Bloom is what usually separates "a 3D render" from "a shot". It runs on the 3D layer
       * only: DOM added in a layer above stays crisp. */
      bloom(b) {
        const opt = b || {};
        composer = new T.EffectComposer(renderer);
        composer.setSize(size.w, size.h);
        composer.addPass(new T.RenderPass(scene, camera));
        composer.addPass(new T.UnrealBloomPass(
          new T.Vector2(size.w, size.h),
          opt.strength === undefined ? 0.6 : opt.strength,
          opt.radius === undefined ? 0.5 : opt.radius,
          opt.threshold === undefined ? 0.85 : opt.threshold
        ));
        composer.addPass(new T.OutputPass());
        return api;
      },

      /* Re-measure the host. Call it only when the size actually changes, not per frame. */
      fit() {
        const s = sizeOf(o.host, o);
        size.w = s.w; size.h = s.h;
        renderer.setSize(s.w, s.h, false);
        camera.aspect = s.w / s.h;
        camera.updateProjectionMatrix();
        if (composer) composer.setSize(s.w, s.h);
        return api;
      },

      /* The one call that belongs in seek(t), after you have moved things by t. */
      render() {
        if (composer) composer.render();
        else renderer.render(scene, camera);
        return api;
      },

      dispose() {
        if (disposed) return;
        disposed = true;
        if (composer) composer.dispose();
        renderer.dispose();
        scene.traverse((n) => {
          if (n.geometry) n.geometry.dispose();
          if (n.material) [].concat(n.material).forEach((m) => m.dispose && m.dispose());
        });
        if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
    return api;
  }

  /* Real DOM elements placed in 3D space. Useful when the "2D" content is text or an interface
   * that must stay vector-crisp while living on a plane that is tilted or pushed back.
   *
   * Known limit, by design of CSS3DRenderer: the DOM layer is composited above (or below) the
   * WebGL canvas as a whole - you cannot interleave one HTML element between two 3D objects. */
  function css3d(opts) {
    const T = lib();
    const o = opts || {};
    const host = hostOf(o.host);
    const size = sizeOf(o.host, o);
    const renderer = new T.CSS3DRenderer();
    renderer.setSize(size.w, size.h);
    renderer.domElement.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;" + (o.css || "");
    host.appendChild(renderer.domElement);

    const scene = new T.Scene();
    const cam = o.camera || {};
    const camera = new T.PerspectiveCamera(cam.fov || 40, size.w / size.h, 1, cam.far || 5000);
    const p = cam.position || [0, 0, 800];
    camera.position.set(p[0], p[1], p[2]);
    const look = cam.lookAt || [0, 0, 0];
    camera.lookAt(look[0], look[1], look[2]);

    const DEG = Math.PI / 180;
    const api = {
      THREE: T, renderer, scene, camera, size,
      domElement: renderer.domElement,

      /* Wrap a real element: object(el, { position:[x,y,z], rotation:[rx,ry,rz] in degrees, scale }) */
      object(el, spec) {
        const s = spec || {};
        const obj = new T.CSS3DObject(el);
        if (s.position) obj.position.set(s.position[0], s.position[1], s.position[2]);
        if (s.rotation) obj.rotation.set(s.rotation[0] * DEG, s.rotation[1] * DEG, s.rotation[2] * DEG);
        if (s.scale) obj.scale.setScalar(s.scale);
        scene.add(obj);
        return obj;
      },

      fit() {
        const s = sizeOf(o.host, o);
        size.w = s.w; size.h = s.h;
        renderer.setSize(s.w, s.h);
        camera.aspect = s.w / s.h;
        camera.updateProjectionMatrix();
        return api;
      },

      render() {
        renderer.render(scene, camera);
        return api;
      }
    };
    return api;
  }

  if (!global.Scene) {
    throw new Error("three-kit.js has to load after scene.js");
  }
  global.Scene.three = view;
  global.Scene.css3d = css3d;
  global.Scene.surface = surface;
})(window);
