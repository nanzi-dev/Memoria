/* eslint-disable react/no-unknown-property */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, extend, useFrame } from '@react-three/fiber';
import { useGLTF, useTexture, Environment, Lightformer } from '@react-three/drei';
import { BallCollider, CuboidCollider, Physics, RigidBody, useRopeJoint, useSphericalJoint } from '@react-three/rapier';
import { MeshLineGeometry, MeshLineMaterial } from 'meshline';

import cardGLB from '../assets/card.glb';
import lanyardBand from '../assets/lanyard-band.png';

import * as THREE from 'three';
import './Lanyard.css';

extend({ MeshLineGeometry, MeshLineMaterial });

// roundRect polyfill
if (!CanvasRenderingContext2D.prototype.roundRect) {
  CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, r) {
    if (typeof r === 'number') r = { tl: r, tr: r, br: r, bl: r };
    this.beginPath();
    this.moveTo(x + r.tl, y);
    this.lineTo(x + w - r.tr, y);
    this.quadraticCurveTo(x + w, y, x + w, y + r.tr);
    this.lineTo(x + w, y + h - r.br);
    this.quadraticCurveTo(x + w, y + h, x + w - r.br, y + h);
    this.lineTo(x + r.bl, y + h);
    this.quadraticCurveTo(x, y + h, x, y + h - r.bl);
    this.lineTo(x, y + r.tl);
    this.quadraticCurveTo(x, y, x + r.tl, y);
    this.closePath();
    return this;
  };
}

const BLANK_PIXEL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

const FRONT_UV_RECT = { x: 0, y: 0, w: 0.5, h: 0.755 };
const BACK_UV_RECT = { x: 0.5, y: 0, w: 0.5, h: 0.757 };

// Generate front face texture: name + avatar + tagline on white card
function createFrontFace({ avatarUrl, name, gender, loadedImg }) {
  var W = 512, H = 512;
  var canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  var ctx = canvas.getContext('2d');

  // White background
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, W, H);

  // Subtle decorative top stripe
  ctx.fillStyle = '#2D2A35'; ctx.fillRect(0, 0, W, 6);

  var padding = 120;
  // UV rect starts ~12.5% into the canvas; push content further down
  var nameY = 110;
  var underlineY = nameY + 52;

  // ── Name: large, bold, left-aligned ──
  var nameText = name || 'UNNAMED';
  ctx.fillStyle = '#1A1A1A';
  ctx.font = 'bold 46px "ZCOOL XiaoWei", "Noto Serif SC", serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(nameText, padding, nameY);

  // Name underline
  var nameWidth = ctx.measureText(nameText).width;
  ctx.strokeStyle = '#2D2A35'; ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padding, underlineY);
  ctx.lineTo(padding + nameWidth, underlineY);
  ctx.stroke();

  // ── Avatar: large, centered, rounded, with border ──
  var avatarSize = 180;
  var avatarX = (W - avatarSize) / 2;
  var avatarY = underlineY + 36;
  var avatarRadius = 12;

  // Shadow behind avatar
  ctx.shadowColor = 'rgba(0,0,0,0.10)';
  ctx.shadowBlur = 16;
  ctx.shadowOffsetX = 0;
  ctx.shadowOffsetY = 4;
  ctx.fillStyle = '#FFFFFF';
  ctx.roundRect(avatarX, avatarY, avatarSize, avatarSize, avatarRadius);
  ctx.fill();
  ctx.shadowColor = 'transparent';
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;

  // Avatar border
  ctx.strokeStyle = '#D5D5D5'; ctx.lineWidth = 2;
  ctx.stroke();

  // Placeholder or image
  if (loadedImg && loadedImg.complete && loadedImg.naturalWidth > 0) {
    ctx.save();
    ctx.roundRect(avatarX, avatarY, avatarSize, avatarSize, avatarRadius);
    ctx.clip();
    var s = Math.max(avatarSize / loadedImg.width, avatarSize / loadedImg.height);
    var dw = loadedImg.width * s;
    var dh = loadedImg.height * s;
    ctx.drawImage(loadedImg,
      avatarX + (avatarSize - dw) / 2,
      avatarY + (avatarSize - dh) / 2,
      dw, dh);
    ctx.restore();
  } else {
    // Placeholder icon
    ctx.fillStyle = '#D0D0D0';
    ctx.font = '56px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('?', avatarX + avatarSize / 2, avatarY + avatarSize / 2);
  }

  // ── Bottom: tagline ──
  var bottomY = avatarY + avatarSize + 60;
  ctx.fillStyle = '#451717';
  ctx.font = 'bold 14px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('MEMORIA', W / 2, bottomY);

  ctx.fillStyle = '#8A8495';
  ctx.font = '12px sans-serif';
  ctx.fillText('Where memories become stories.', W / 2, bottomY + 22);

  // Subtle decorative bottom stripe
  ctx.fillStyle = '#2D2A35';
  ctx.fillRect(0, H - 6, W, 6);

  return canvas.toDataURL('image/png');
}
function createBackFace() {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#F2EDE4'; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#2D2A35'; ctx.fillRect(0, 0, W, 6);
  ctx.fillStyle = '#2D2A35'; ctx.fillRect(0, H - 6, W, 6);
  ctx.strokeStyle = 'rgba(45,42,53,0.2)'; ctx.lineWidth = 1;
  ctx.roundRect(8, 8, W - 16, H - 16, 6); ctx.stroke();

  const cx = W / 2, cy = H / 2 - 10, d = 60;
  ctx.strokeStyle = 'rgba(100,95,110,0.25)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx, cy - d); ctx.lineTo(cx + d * 0.6, cy);
  ctx.lineTo(cx, cy + d); ctx.lineTo(cx - d * 0.6, cy); ctx.closePath(); ctx.stroke();
  ctx.fillStyle = '#5A5268'; ctx.font = 'bold 20px "JetBrains Mono", monospace';
  ctx.textAlign = 'center'; ctx.fillText('MEMORIA', cx, cy);
  ctx.fillStyle = '#8A8495'; ctx.font = '11px "JetBrains Mono", monospace';
  ctx.fillText('CHARACTER ARCHIVE', cx, cy + 30);

  return canvas.toDataURL('image/png');
}

function Band({
  maxSpeed = 15, minSpeed = 0, isMobile = false,
  frontImage = null, backImage = null, imageFit = 'cover',
  lanyardImage = null, lanyardWidth = 1
}) {
  const band = useRef(null), fixed = useRef(null), j1 = useRef(null),
    j2 = useRef(null), j3 = useRef(null), card = useRef(null);
  const vec = new THREE.Vector3(), ang = new THREE.Vector3(),
    rot = new THREE.Vector3(), dir = new THREE.Vector3();
  const segmentProps = { type: 'dynamic', canSleep: true, colliders: false, angularDamping: 2, linearDamping: 2 };
  const { nodes, materials } = useGLTF(cardGLB);
  const texture = useTexture(lanyardImage || lanyardBand);
  const frontTex = useTexture(frontImage || BLANK_PIXEL);
  const backTex = useTexture(backImage || BLANK_PIXEL);

  const cardMap = useMemo(() => {
    const baseMap = materials.base.map;
    if (!frontImage && !backImage) return baseMap;
    const baseImg = baseMap.image; if (!baseImg) return baseMap;
    const W = baseImg.width, H = baseImg.height;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d'); if (!ctx) return baseMap;
    ctx.drawImage(baseImg, 0, 0, W, H);

    const drawFitted = (img, rect) => {
      const rx = rect.x * W, ry = rect.y * H, rw = rect.w * W, rh = rect.h * H;
      const pick = imageFit === 'contain' ? Math.min : Math.max;
      const scale = pick(rw / img.width, rh / img.height);
      const dw = img.width * scale, dh = img.height * scale;
      ctx.save(); ctx.beginPath(); ctx.rect(rx, ry, rw, rh); ctx.clip();
      ctx.drawImage(img, rx + (rw - dw) / 2, ry + (rh - dh) / 2, dw, dh);
      ctx.restore();
    };
    if (frontImage && frontTex.image) drawFitted(frontTex.image, FRONT_UV_RECT);
    if (backImage && backTex.image) drawFitted(backTex.image, BACK_UV_RECT);

    const composite = new THREE.CanvasTexture(canvas);
    composite.colorSpace = THREE.SRGBColorSpace; composite.flipY = baseMap.flipY;
    composite.anisotropy = 16; composite.needsUpdate = true;
    return composite;
  }, [frontImage, backImage, imageFit, frontTex, backTex, materials.base.map]);

  const [curve] = useState(() => new THREE.CatmullRomCurve3([new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()]));
  const [dragged, drag] = useState(false);
  const [hovered, hover] = useState(false);

  useRopeJoint(fixed, j1, [[0, 0, 0], [0, 0, 0], 1]);
  useRopeJoint(j1, j2, [[0, 0, 0], [0, 0, 0], 1]);
  useRopeJoint(j2, j3, [[0, 0, 0], [0, 0, 0], 1]);
  useSphericalJoint(j3, card, [[0, 0, 0], [0, 3.2, 0]]);

  useEffect(() => {
    if (hovered) {
      document.body.style.cursor = dragged ? 'grabbing' : 'grab';
      return () => { document.body.style.cursor = 'auto'; };
    }
  }, [hovered, dragged]);

  // Wind timer ref for gentle random breeze
  const windTimer = useRef(0);
  const nextBreezeTime = useRef(15 + Math.random() * 20);

  useFrame((state, delta) => {
    const cdt = Math.min(delta, 0.1);
    if (dragged) {
      vec.set(state.pointer.x, state.pointer.y, 0.5).unproject(state.camera);
      dir.copy(vec).sub(state.camera.position).normalize();
      vec.add(dir.multiplyScalar(state.camera.position.length()));
      [card, j1, j2, j3, fixed].forEach(ref => ref.current?.wakeUp());
      card.current?.setNextKinematicTranslation({ x: vec.x - dragged.x, y: vec.y - dragged.y, z: vec.z - dragged.z });
    }

    // Gentle breeze: per-card random phase + slow drift for uniqueness
    if (card.current && !dragged) {
      windTimer.current += cdt;
      const t = windTimer.current;
      // Per-card random phases (set once via ref)
      if (!card._breezePhases) {
        card._breezePhases = [
          Math.random() * Math.PI * 2,
          Math.random() * Math.PI * 2,
          Math.random() * Math.PI * 2,
          Math.random() * Math.PI * 2,
          Math.random() * Math.PI * 2,
          Math.random() * Math.PI * 2,
        ];
        card._breezeFreqs = [
          0.2 + Math.random() * 0.3,
          0.15 + Math.random() * 0.25,
          0.18 + Math.random() * 0.28,
          0.12 + Math.random() * 0.22,
          0.1 + Math.random() * 0.2,
          0.08 + Math.random() * 0.18,
        ];
      }
      const p = card._breezePhases;
      const f = card._breezeFreqs;
      const swayX = Math.sin(t * f[0] + p[0]) * 0.02 + Math.sin(t * f[1] + p[1]) * 0.014;
      const swayY = Math.cos(t * f[2] + p[2]) * 0.008 + Math.sin(t * f[3] + p[3]) * 0.006;
      const swayZ = Math.sin(t * f[4] + p[4]) * 0.006 + Math.cos(t * f[5] + p[5]) * 0.004;
      const vel = card.current.linvel();
      card.current.setLinvel({
        x: vel.x + swayX,
        y: vel.y + swayY,
        z: vel.z + swayZ,
      }, true);
      card.current.setAngvel({
        x: swayY * 0.3,
        y: -swayX * 0.3,
        z: swayZ * 0.5,
      }, true);
    }

    if (fixed.current) {
      [j1, j2].forEach(ref => {
        if (!ref.current.lerped) ref.current.lerped = new THREE.Vector3().copy(ref.current.translation());
        const cd = Math.max(0.01, Math.min(0.3, ref.current.lerped.distanceTo(ref.current.translation())));
        ref.current.lerped.lerp(ref.current.translation(), delta * (minSpeed + cd * (maxSpeed - minSpeed)));
      });
      curve.points[0].copy(j3.current.translation());
      curve.points[1].copy(j2.current.lerped);
      curve.points[2].copy(j1.current.lerped);
      curve.points[3].copy(fixed.current.translation());
      band.current.geometry.setPoints(curve.getPoints(isMobile ? 16 : 32));
      ang.copy(card.current.angvel()); rot.copy(card.current.rotation());
      card.current.setAngvel({ x: ang.x, y: ang.y - rot.y * 0.25, z: ang.z });
    }
  });

  curve.curveType = 'chordal'; texture.wrapS = texture.wrapT = THREE.RepeatWrapping;

  return (
    <>
      <group position={[0, 5.3, 0]}>
        <RigidBody ref={fixed} {...segmentProps} type="fixed" />
        <RigidBody position={[0.15, 0, 0]} ref={j1} {...segmentProps}><BallCollider args={[0.06]} /></RigidBody>
        <RigidBody position={[0.30, 0, 0]} ref={j2} {...segmentProps}><BallCollider args={[0.06]} /></RigidBody>
        <RigidBody position={[0.45, 0, 0]} ref={j3} {...segmentProps}><BallCollider args={[0.06]} /></RigidBody>
        <RigidBody position={[0.60, 0, 0]} ref={card} {...segmentProps} type={dragged ? 'kinematicPosition' : 'dynamic'}>
          <CuboidCollider args={[0.8, 1.125, 0.01]} />
          <group scale={3.6} position={[0, -1.2, -0.05]}
            onPointerOver={() => hover(true)} onPointerOut={() => hover(false)}
            onPointerUp={e => { e.target.releasePointerCapture(e.pointerId); drag(false); }}
            onPointerDown={e => {
              e.target.setPointerCapture(e.pointerId);
              drag(new THREE.Vector3().copy(e.point).sub(vec.copy(card.current.translation())));
            }}>
            <mesh geometry={nodes.card.geometry}>
              <meshPhysicalMaterial map={cardMap} map-anisotropy={16} clearcoat={isMobile ? 0 : 1}
                clearcoatRoughness={0.15} roughness={0.9} metalness={0.8} />
            </mesh>
            <mesh geometry={nodes.clip.geometry} material={materials.metal} material-roughness={0.3} />
            <mesh geometry={nodes.clamp.geometry} material={materials.metal} />
          </group>
        </RigidBody>
      </group>
      <mesh ref={band}>
        <meshLineGeometry />
        <meshLineMaterial color="white" depthTest={false}
          resolution={isMobile ? [1000, 2000] : [1000, 1000]}
          useMap map={texture} repeat={[-4, 1]} lineWidth={0.8} />
      </mesh>
    </>
  );
}

export default function Lanyard({ characterInfo = {}, className = '', style = {} }) {
  const { avatarUrl, name, gender } = characterInfo;
  var _a = useState(null), loadedImg = _a[0], setLoadedImg = _a[1];

  useEffect(function() {
    setLoadedImg(null);
    if (!avatarUrl) return;
    var img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function() { setLoadedImg(img); };
    img.onerror = function() { setLoadedImg(null); };
    img.src = avatarUrl;
  }, [avatarUrl]);

  var frontImage = useMemo(function() {
    return createFrontFace({ avatarUrl: avatarUrl, name: name, gender: gender, loadedImg: loadedImg });
  }, [name, gender, loadedImg]);
  const backImage = useMemo(() => createBackFace(), []);

  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768);
  useEffect(() => {
    const h = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, []);

  return (
    <div className={`lanyard-wrapper ${className}`} style={{ width: "100%", height: "100%", overflow: "hidden", ...style }}>
      <Canvas camera={{ position: [0, 0, 13], fov: 22 }} dpr={[1, isMobile ? 1.5 : 2]}
        gl={{ alpha: true, antialias: true }} onCreated={({ gl }) => gl.setClearColor(new THREE.Color(0x000000), 0)}>
        <ambientLight intensity={Math.PI} />
        <Physics gravity={[0, -40, 0]} timeStep={isMobile ? 1 / 30 : 1 / 60}>
          <Band isMobile={isMobile} frontImage={frontImage} backImage={backImage} imageFit="cover" />
        </Physics>
        <Environment blur={0.75}>
          <Lightformer intensity={2} color="#A7EF9E" position={[0, -1, 5]} rotation={[0, 0, Math.PI / 3]} scale={[100, 0.1, 1]} />
          <Lightformer intensity={3} color="#A7EF9E" position={[-1, -1, 1]} rotation={[0, 0, Math.PI / 3]} scale={[100, 0.1, 1]} />
          <Lightformer intensity={3} color="#A7EF9E" position={[1, 1, 1]} rotation={[0, 0, Math.PI / 3]} scale={[100, 0.1, 1]} />
          <Lightformer intensity={10} color="#A7EF9E" position={[-10, 0, 14]} rotation={[0, Math.PI / 2, Math.PI / 3]} scale={[100, 10, 1]} />
        </Environment>
      </Canvas>
    </div>
  );
}
