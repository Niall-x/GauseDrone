// Gaussian splat viewer built on Spark (three.js). Owned by the app rather
// than embedded, so it can grow drone-specific overlays: the capture
// trajectory and camera frustums are drawn today; coverage heatmaps or a VIO
// vs SfM trajectory comparison slot in the same way later.
import { SparkRenderer, SplatEdit, SplatEditSdf, SplatEditSdfType, SplatMesh } from "@sparkjsdev/spark";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { ViewerControls } from "./controls";

export interface ViewCamera {
  name: string;
  position: [number, number, number];
  forward: [number, number, number];
  up: [number, number, number];
}

export interface ViewInfo {
  up: [number, number, number];
  center: [number, number, number];
  bounds: [[number, number, number], [number, number, number]];
  /** Extent of the sparse points along "up", relative to `center` (older exports lack it). */
  height_range?: [number, number];
  fov_y_deg: number;
  cameras: ViewCamera[];
}

export interface ViewerStats {
  fps: number;
  splats: number;
}

export interface SplatViewerHandle {
  goToCamera(index: number): void;
  resetView(): void;
  overview(): void;
  screenshot(): Promise<Blob | null>;
}

interface Props {
  url: string;
  view: ViewInfo;
  showTrajectory: boolean;
  showFrustums: boolean;
  /** Hide everything above this fraction of the scene's height (null = off), to see into a room from above. */
  cutaway: number | null;
  /** Mouse drag (look/orbit) and scroll multipliers; 1 = default. */
  lookSensitivity: number;
  scrollSensitivity: number;
  onProgress?: (fraction: number | null) => void;
  onLoaded?: () => void;
  onError?: (message: string) => void;
  onStats?: (stats: ViewerStats) => void;
}

const v3 = (a: number[]) => new THREE.Vector3(a[0], a[1], a[2]);

export const SplatViewer = forwardRef<SplatViewerHandle, Props>(function SplatViewer(props, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const propsRef = useRef(props);
  propsRef.current = props;
  const api = useRef<
    SplatViewerHandle & {
      setOverlays(t: boolean, f: boolean): void;
      setCutaway(f: number | null): void;
      setSensitivity(look: number, scroll: number): void;
    }
  >(null);

  useImperativeHandle(ref, () => ({
    goToCamera: (i) => api.current?.goToCamera(i),
    resetView: () => api.current?.resetView(),
    overview: () => api.current?.overview(),
    screenshot: () => api.current?.screenshot() ?? Promise.resolve(null),
  }));

  useEffect(() => {
    const container = containerRef.current!;
    const { url, view } = propsRef.current;

    const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0b0d10);
    container.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.outline = "none";
    renderer.domElement.tabIndex = 0;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(view.fov_y_deg || 60, 1, 0.01, 2000);
    const spark = new SparkRenderer({ renderer });
    scene.add(spark);

    // COLMAP's world frame has no meaningful up or origin. Rotate the
    // estimated capture "up" onto three.js +Y and centre on the cameras.
    const world = new THREE.Group();
    world.quaternion.setFromUnitVectors(v3(view.up).normalize(), new THREE.Vector3(0, 1, 0));
    world.position.copy(v3(view.center).applyQuaternion(world.quaternion).negate());
    world.updateMatrixWorld(true);
    scene.add(world);

    const lo = v3(view.bounds[0]);
    const hi = v3(view.bounds[1]);
    const extent = Math.max(hi.clone().sub(lo).length(), 1e-3);

    const splat = new SplatMesh({
      url,
      onProgress: (e) => propsRef.current.onProgress?.(e.lengthComputable ? e.loaded / e.total : null),
    });
    world.add(splat);
    splat.initialized
      .then(() => {
        propsRef.current.onProgress?.(1);
        propsRef.current.onLoaded?.();
      })
      .catch((e: unknown) => propsRef.current.onError?.(String(e)));

    // Cutaway: a plane edit whose local +z points down; splats on its far
    // side (above it) get opacity 0. Parked far overhead when off.
    const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((i) =>
      new THREE.Vector3(i & 1 ? hi.x : lo.x, i & 2 ? hi.y : lo.y, i & 4 ? hi.z : lo.z).applyMatrix4(world.matrixWorld),
    );
    const [yMin, yMax] = view.height_range ?? [Math.min(...corners.map((c) => c.y)), Math.max(...corners.map((c) => c.y))];
    const cutEdit = new SplatEdit({ softEdge: extent * 0.01 });
    const cutPlane = new SplatEditSdf({ type: SplatEditSdfType.PLANE, opacity: 0 });
    cutPlane.rotation.x = Math.PI / 2;
    cutEdit.addSdf(cutPlane);
    cutEdit.add(cutPlane);
    scene.add(cutEdit);
    const setCutaway = (f: number | null) => {
      cutPlane.position.y = f == null ? 1e9 : yMin + f * (yMax - yMin);
    };

    // --- trajectory + frustum overlays (in COLMAP coordinates, inside `world`) ---
    const positions = view.cameras.map((c) => v3(c.position));
    const trajectory = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(positions),
      new THREE.LineBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: 0.9, depthTest: false }),
    );
    trajectory.renderOrder = 10;
    world.add(trajectory);

    const size = extent * 0.012;
    const aspect = 1.5;
    const tanY = Math.tan(THREE.MathUtils.degToRad((view.fov_y_deg || 60) / 2));
    const pts: THREE.Vector3[] = [];
    for (const c of view.cameras) {
      const o = v3(c.position);
      const f = v3(c.forward).normalize();
      const u = v3(c.up).normalize();
      const r = new THREE.Vector3().crossVectors(f, u).normalize();
      const centre = o.clone().addScaledVector(f, size);
      const dy = u.clone().multiplyScalar(size * tanY);
      const dx = r.clone().multiplyScalar(size * tanY * aspect);
      const corners = [
        centre.clone().add(dx).add(dy),
        centre.clone().sub(dx).add(dy),
        centre.clone().sub(dx).sub(dy),
        centre.clone().add(dx).sub(dy),
      ];
      for (let i = 0; i < 4; i++) pts.push(o, corners[i], corners[i], corners[(i + 1) % 4]);
    }
    const frustums = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: 0xfbbf24, transparent: true, opacity: 0.55, depthTest: false }),
    );
    frustums.renderOrder = 11;
    world.add(frustums);

    const highlight = new THREE.Mesh(
      new THREE.SphereGeometry(size * 0.35, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xf87171, depthTest: false }),
    );
    highlight.renderOrder = 12;
    highlight.visible = false;
    world.add(highlight);

    // --- controls: one scheme, see ./controls.ts ---
    const controls = new ViewerControls(camera, renderer.domElement, {
      moveSpeed: extent * 0.15,
      focusDistance: extent * 0.3,
      minFocus: extent * 0.01,
    });

    const toWorld = (p: THREE.Vector3) => p.clone().applyMatrix4(world.matrixWorld);
    const dirToWorld = (d: THREE.Vector3) => d.clone().applyQuaternion(world.quaternion).normalize();

    const goToCamera = (i: number) => {
      const c = view.cameras[i];
      if (!c) return;
      const pos = toWorld(v3(c.position));
      const fwd = dirToWorld(v3(c.forward));
      camera.position.copy(pos);
      camera.up.set(0, 1, 0);
      // Focus (what right-drag orbits) on the point along the view ray nearest the scene centre (the
      // world origin): for a room filmed from inside that is close to the camera, so orbiting looks
      // around the room instead of swinging the camera through a wall; for an object orbit it lands on the object.
      const focus = Math.max(-pos.dot(fwd), extent * 0.05);
      controls.lookAt(pos.clone().addScaledVector(fwd, focus));
      highlight.position.copy(v3(c.position));
      highlight.visible = true;
    };

    // Bird's-eye view from above and outside the capture, for judging coverage.
    const overview = () => {
      const size = hi.clone().sub(lo).applyQuaternion(world.quaternion);
      const radius = 0.5 * Math.hypot(size.x, size.z);
      const dist = radius / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.9;
      camera.up.set(0, 1, 0);
      camera.position.set(0, dist * 0.8, dist * 0.6);
      controls.lookAt(new THREE.Vector3(0, 0, 0));
      highlight.visible = false;
    };

    const resetView = () => {
      goToCamera(0);
      highlight.visible = false;
    };

    // Double-click a surface to orbit around it.
    const raycaster = new THREE.Raycaster();
    const onDblClick = (e: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      const hit = raycaster.intersectObject(splat, false)[0];
      if (hit) controls.lookAt(hit.point);
    };
    renderer.domElement.addEventListener("dblclick", onDblClick);

    const screenshot = () =>
      new Promise<Blob | null>((resolve) => {
        renderer.render(scene, camera);
        renderer.domElement.toBlob(resolve, "image/png");
      });

    api.current = {
      goToCamera,
      resetView,
      overview,
      screenshot,
      setOverlays: (t, f) => {
        trajectory.visible = t;
        frustums.visible = f;
      },
      setCutaway,
      setSensitivity: (look, scroll) => {
        controls.lookSensitivity = look;
        controls.scrollSensitivity = scroll;
      },
    };
    setCutaway(propsRef.current.cutaway);
    api.current.setSensitivity(propsRef.current.lookSensitivity, propsRef.current.scrollSensitivity);
    api.current.setOverlays(propsRef.current.showTrajectory, propsRef.current.showFrustums);
    resetView();

    // --- sizing + render loop ---
    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = `${w}px`;
      renderer.domElement.style.height = `${h}px`;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    resize();

    let frames = 0;
    let lastStats = performance.now();
    let lastFrame = performance.now();
    renderer.setAnimationLoop(() => {
      const now = performance.now();
      controls.update(Math.min(0.1, (now - lastFrame) / 1000)); // clamp: no leap after a background tab
      lastFrame = now;
      renderer.render(scene, camera);
      frames++;
      const t = performance.now();
      if (t - lastStats > 1000) {
        propsRef.current.onStats?.({ fps: (frames * 1000) / (t - lastStats), splats: splat.splats?.getNumSplats() ?? 0 });
        frames = 0;
        lastStats = t;
      }
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      renderer.domElement.removeEventListener("dblclick", onDblClick);
      controls.dispose();
      splat.dispose();
      for (const obj of [trajectory, frustums, highlight]) {
        obj.geometry.dispose();
        (obj.material as THREE.Material).dispose();
      }
      renderer.dispose();
      // Browsers cap live WebGL contexts (~16); release this one now rather than at GC.
      renderer.forceContextLoss();
      renderer.domElement.remove();
      api.current = null;
    };
    // The scene is rebuilt only when the file changes; overlays update in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.url]);

  useEffect(() => api.current?.setOverlays(props.showTrajectory, props.showFrustums), [props.showTrajectory, props.showFrustums]);
  useEffect(() => api.current?.setCutaway(props.cutaway), [props.cutaway]);
  useEffect(
    () => api.current?.setSensitivity(props.lookSensitivity, props.scrollSensitivity),
    [props.lookSensitivity, props.scrollSensitivity],
  );

  return <div ref={containerRef} className="absolute inset-0" />;
});
