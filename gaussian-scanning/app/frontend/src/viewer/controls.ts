// One control scheme, all usable at once (like a game / editor fly camera):
//   WASD / arrows move · E/Space up · Q/C down · Shift faster · scroll moves forward/back
//   left-drag look around · right-drag orbit the focus point · middle-drag pan
// World "up" is +Y (the viewer rotates the scene so), so the camera never rolls.
import * as THREE from "three";

const LOOK_RAD_PER_PX = 0.003;
const MAX_PITCH = THREE.MathUtils.degToRad(89);
const SHIFT_MULTIPLIER = 3;
const ACCEL = 12; // how quickly movement eases in/out (1/s)

const MOVE_KEYS: Record<string, [number, number, number]> = {
  KeyW: [0, 0, -1], ArrowUp: [0, 0, -1],
  KeyS: [0, 0, 1], ArrowDown: [0, 0, 1],
  KeyA: [-1, 0, 0], ArrowLeft: [-1, 0, 0],
  KeyD: [1, 0, 0], ArrowRight: [1, 0, 0],
  KeyE: [0, 1, 0], Space: [0, 1, 0],
  KeyQ: [0, -1, 0], KeyC: [0, -1, 0],
};

type Drag = "look" | "orbit" | "pan";

export class ViewerControls {
  /** Units per second at normal speed. */
  moveSpeed: number;
  /** Distance ahead of the camera that right-drag orbits around and scroll zooms towards. */
  focusDistance: number;
  enabled = true;

  private yaw = 0;
  private pitch = 0;
  private keys = new Set<string>();
  private velocity = new THREE.Vector3();
  private drag: { kind: Drag; x: number; y: number; id: number; focus: THREE.Vector3 } | null = null;
  private readonly minFocus: number;
  private readonly cleanup: (() => void)[] = [];

  constructor(
    private camera: THREE.PerspectiveCamera,
    private canvas: HTMLCanvasElement,
    { moveSpeed, focusDistance, minFocus }: { moveSpeed: number; focusDistance: number; minFocus: number },
  ) {
    this.moveSpeed = moveSpeed;
    this.focusDistance = focusDistance;
    this.minFocus = minFocus;
    this.syncFromCamera();

    const on = <K extends keyof WindowEventMap>(target: Window | HTMLElement, type: K, fn: (e: WindowEventMap[K]) => void, opts?: AddEventListenerOptions) => {
      target.addEventListener(type, fn as EventListener, opts);
      this.cleanup.push(() => target.removeEventListener(type, fn as EventListener, opts));
    };
    on(window, "keydown", (e) => {
      if (!this.enabled || isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.code in MOVE_KEYS || e.code.startsWith("Shift")) {
        this.keys.add(e.code);
        if (e.code in MOVE_KEYS) e.preventDefault();
      }
    });
    on(window, "keyup", (e) => this.keys.delete(e.code));
    on(window, "blur", () => this.keys.clear()); // no stuck keys after alt-tab
    on(canvas, "contextmenu", (e) => e.preventDefault());
    on(canvas, "pointerdown", (e) => {
      if (!this.enabled || this.drag) return;
      const kind: Drag = e.button === 2 ? "orbit" : e.button === 1 ? "pan" : "look";
      e.preventDefault(); // no middle-click autoscroll
      canvas.setPointerCapture(e.pointerId);
      canvas.focus();
      this.drag = { kind, x: e.clientX, y: e.clientY, id: e.pointerId, focus: this.focusPoint() };
    });
    on(canvas, "pointermove", (e) => {
      const d = this.drag;
      if (!d || e.pointerId !== d.id) return;
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      d.x = e.clientX;
      d.y = e.clientY;
      if (d.kind === "look") this.rotate(-dx * LOOK_RAD_PER_PX, -dy * LOOK_RAD_PER_PX);
      else if (d.kind === "orbit") this.orbit(d.focus, -dx * LOOK_RAD_PER_PX, -dy * LOOK_RAD_PER_PX);
      else this.pan(dx, dy, d.focus);
    });
    const endDrag = (e: PointerEvent) => {
      if (this.drag?.id === e.pointerId) this.drag = null;
    };
    on(canvas, "pointerup", endDrag);
    on(canvas, "pointercancel", endDrag);
    on(
      canvas,
      "wheel",
      (e) => {
        if (!this.enabled) return;
        e.preventDefault();
        // Move towards the focus point, proportionally to how far it is: fast from afar, fine close up.
        const deltaPx = THREE.MathUtils.clamp(e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY, -200, 200); // Firefox scrolls in lines
        const step = this.focusDistance * (1 - Math.exp(-deltaPx * 0.0015));
        const forward = this.forward();
        this.camera.position.addScaledVector(forward, -step);
        this.focusDistance = Math.max(this.minFocus, this.focusDistance + step);
      },
      { passive: false },
    );
  }

  update(dt: number): void {
    const target = new THREE.Vector3();
    if (this.enabled) for (const code of this.keys) if (MOVE_KEYS[code]) target.add(new THREE.Vector3(...MOVE_KEYS[code]));
    if (target.lengthSq() > 0) {
      const fast = this.keys.has("ShiftLeft") || this.keys.has("ShiftRight");
      target.normalize().multiplyScalar(this.moveSpeed * (fast ? SHIFT_MULTIPLIER : 1));
    }
    this.velocity.lerp(target, 1 - Math.exp(-ACCEL * dt));
    if (this.velocity.lengthSq() < 1e-10) return;
    // W/S fly along the view direction; A/D strafe level; E/Q go straight up/down in the world.
    const right = new THREE.Vector3(1, 0, 0).applyEuler(new THREE.Euler(0, this.yaw, 0, "YXZ"));
    const move = this.forward()
      .multiplyScalar(-this.velocity.z)
      .addScaledVector(right, this.velocity.x)
      .add(new THREE.Vector3(0, this.velocity.y, 0));
    this.camera.position.addScaledVector(move, dt);
  }

  /** Aim the camera at a world point, keeping it where it is; that point becomes the orbit focus. */
  lookAt(point: THREE.Vector3): void {
    this.camera.lookAt(point);
    this.focusDistance = Math.max(this.minFocus, this.camera.position.distanceTo(point));
    this.syncFromCamera();
  }

  /** Call after moving/rotating the camera from outside (camera snaps, overview). */
  syncFromCamera(): void {
    const e = new THREE.Euler().setFromQuaternion(this.camera.quaternion, "YXZ");
    this.yaw = e.y;
    this.pitch = THREE.MathUtils.clamp(e.x, -MAX_PITCH, MAX_PITCH);
    this.velocity.set(0, 0, 0);
    this.apply();
  }

  dispose(): void {
    this.cleanup.forEach((fn) => fn());
    this.keys.clear();
  }

  private forward(): THREE.Vector3 {
    return new THREE.Vector3(0, 0, -1).applyQuaternion(this.camera.quaternion);
  }

  private focusPoint(): THREE.Vector3 {
    return this.camera.position.clone().addScaledVector(this.forward(), this.focusDistance);
  }

  private apply(): void {
    this.camera.quaternion.setFromEuler(new THREE.Euler(this.pitch, this.yaw, 0, "YXZ"));
  }

  private rotate(dYaw: number, dPitch: number): void {
    this.yaw += dYaw;
    this.pitch = THREE.MathUtils.clamp(this.pitch + dPitch, -MAX_PITCH, MAX_PITCH);
    this.apply();
  }

  private orbit(focus: THREE.Vector3, dYaw: number, dPitch: number): void {
    this.rotate(dYaw, dPitch);
    // Stay the same distance from the focus, on the far side of the new view direction.
    this.camera.position.copy(focus).addScaledVector(this.forward(), -this.focusDistance);
  }

  private pan(dx: number, dy: number, focus: THREE.Vector3): void {
    // Keep the point at the focus distance under the cursor.
    const perPx = (2 * this.focusDistance * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) / this.canvas.clientHeight;
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(this.camera.quaternion);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(this.camera.quaternion);
    const shift = right.multiplyScalar(-dx * perPx).addScaledVector(up, dy * perPx);
    this.camera.position.add(shift);
    focus.add(shift);
  }
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  if (t.isContentEditable || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return true;
  if (t.tagName !== "INPUT") return false;
  const type = (t as HTMLInputElement).type;
  // A focused slider (camera stepper, cutaway) keeps the arrows but shouldn't block WASD.
  if (type === "range") return e.code.startsWith("Arrow");
  return !["checkbox", "radio", "button"].includes(type);
}
