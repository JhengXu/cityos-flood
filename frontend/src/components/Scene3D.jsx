import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { getScene3d } from '../api'

/**
 * Scene3D v2 — 深圳 3D 城市实景（大幅升级）
 *
 * 视觉：天空渐变球 + 半球光照 + 阴影 + 地形分层设色 + 动态水面着色器
 * 动画：入场飞入 + 灾种点脉冲 + 台风螺旋云带旋转 + 路径流光
 * 模拟：降雨粒子系统 + 洪水淹没演进
 * 交互：图层开关 + 视角预设
 */
const LAYER_DEFS = [
  { id: 'buildings', label: '建筑', icon: '🏢', default: true },
  { id: 'points', label: '灾种点', icon: '📍', default: true },
  { id: 'typhoon', label: '台风云带', icon: '🌀', default: false },
  { id: 'rain', label: '降雨粒子', icon: '🌧️', default: false },
  { id: 'floodAnim', label: '洪水演进', icon: '🌊', default: false },
]

const VIEWS = [
  { id: 'overview', label: '全景', pitch: 0.9, dist: 320, icon: '🗺️' },
  { id: 'city', label: '市中心', pitch: 0.45, dist: 140, icon: '🏙️' },
  { id: 'top', label: '俯视', pitch: 1.42, dist: 300, icon: '⬇️' },
  { id: 'close', label: '低空', pitch: 0.2, dist: 90, icon: '✈️' },
]

export default function Scene3D({ typhoonTrack = null, height = 520, showBuildings = true, showPoints = true, alertLevel = 0 }) {
  const mountRef = useRef(null)
  const [status, setStatus] = useState('加载 3D 场景…')
  const [ready, setReady] = useState(false)
  const [layers, setLayers] = useState(() => Object.fromEntries(LAYER_DEFS.map(l => [l.id, l.default])))
  const [view, setView] = useState('overview')
  const sceneRef = useRef(null)
  const engineRef = useRef(null)
  const layersRef = useRef(layers)
  layersRef.current = layers

  // 加载场景数据
  useEffect(() => {
    let mounted = true
    getScene3d({ demStep: 6, buildingMinHeight: 30, buildingLimit: 6000 })
      .then((d) => { if (mounted) { sceneRef.current = d; setReady(true) } })
      .catch(() => setStatus('3D 数据加载失败（后端未启动？）'))
    return () => { mounted = false }
  }, [])

  // three.js 渲染引擎
  useEffect(() => {
    if (!ready || !mountRef.current || !sceneRef.current) return
    const data = sceneRef.current
    const mount = mountRef.current
    const W = mount.clientWidth || 900
    const H = height

    const scene = new THREE.Scene()
    // 天空渐变球
    const skyMat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      uniforms: {
        top: { value: new THREE.Color(0x14264a) },
        mid: { value: new THREE.Color(0x2a5382) },
        bot: { value: new THREE.Color(0x3e6a94) },
      },
      vertexShader: 'varying vec3 vPos; void main(){ vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `varying vec3 vPos; uniform vec3 top; uniform vec3 mid; uniform vec3 bot;
        void main(){ float h = normalize(vPos).y;
          vec3 c = h > 0.0 ? mix(mid, top, pow(h, 0.7)) : mix(mid, bot, pow(-h, 0.5));
          gl_FragColor = vec4(c, 1.0); }`,
    })
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(1400, 24, 16), skyMat))
    scene.fog = new THREE.Fog(0x1e3a5c, 500, 1600)

    const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 4000)
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(W, H, false) // false: 不写死 style 尺寸，由 CSS 100% 控制
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.15
    mount.appendChild(renderer.domElement)

    // 光照
    scene.add(new THREE.HemisphereLight(0xbcd4f0, 0x3a4a5e, 1.0))
    const sun = new THREE.DirectionalLight(0xfff5e0, 1.9)
    sun.position.set(180, 300, 120)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    sun.shadow.camera.left = -300; sun.shadow.camera.right = 300
    sun.shadow.camera.top = 300; sun.shadow.camera.bottom = -300
    sun.shadow.bias = -0.0005
    sun.shadow.intensity = 0.35
    scene.add(sun)
    const rim = new THREE.DirectionalLight(0x6db8ff, 0.65)
    rim.position.set(-200, 120, -160)
    scene.add(rim)

    // 坐标系
    const terrain = data.terrain
    const lon0 = terrain?.lon0 ?? 113.72, lat0 = terrain?.lat0 ?? 22.87
    const lon1 = terrain?.lon1 ?? 114.65, lat1 = terrain?.lat1 ?? 22.44
    const cx = (lon0 + lon1) / 2, cy = (lat0 + lat1) / 2
    const SCALE = 1000
    const toXY = (lon, lat) => [
      (lon - cx) * SCALE * Math.cos((cy * Math.PI) / 180),
      (lat - cy) * SCALE,
    ]

    // 地形（分层设色 + 阴影接收）
    let terrainMesh = null
    if (terrain && terrain.heights) {
      const rows = terrain.shape[0], cols = terrain.shape[1]
      const wSpan = (lon1 - lon0) * SCALE * Math.cos((cy * Math.PI) / 180)
      const hSpan = (lat0 - lat1) * SCALE
      const geo = new THREE.PlaneGeometry(wSpan, hSpan, cols - 1, rows - 1)
      geo.rotateX(-Math.PI / 2)
      const pos = geo.attributes.position
      const colors = new Float32Array(pos.count * 3)
      const bands = [
        { h: -20, c: new THREE.Color(0x123a5f) },
        { h: 0, c: new THREE.Color(0x2563a0) },
        { h: 5, c: new THREE.Color(0x3d8fb5) },
        { h: 25, c: new THREE.Color(0x3f7a4a) },
        { h: 80, c: new THREE.Color(0x5f9a52) },
        { h: 200, c: new THREE.Color(0xa89762) },
        { h: 500, c: new THREE.Color(0xc4b48e) },
        { h: 950, c: new THREE.Color(0xfaf0dc) },
      ]
      const bandColor = (elev) => {
        if (elev <= bands[0].h) return bands[0].c
        for (let i = 1; i < bands.length; i++) {
          if (elev <= bands[i].h) {
            const t = (elev - bands[i - 1].h) / (bands[i].h - bands[i - 1].h)
            return bands[i - 1].c.clone().lerp(bands[i].c, t)
          }
        }
        return bands[bands.length - 1].c
      }
      const noise = (x, y) => Math.sin(x * 0.7) * Math.cos(y * 0.5) * 0.6 + Math.sin(x * 1.3 + y * 0.8) * 0.3
      for (let i = 0; i < pos.count; i++) {
        const r = Math.floor(i / cols), c = i % cols
        const elev = terrain.heights[r][c] || 0
        const jitter = noise(c * 0.1, r * 0.1)
        pos.setY(i, Math.max(elev, 0) * 0.096 + (elev > 1 ? jitter : 0))
        const col = bandColor(elev + jitter * 4)
        colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b
      }
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      geo.computeVertexNormals()
      terrainMesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.9, metalness: 0.02,
        emissive: 0x0a1018, emissiveIntensity: 0.3,
      }))
      terrainMesh.receiveShadow = true
      scene.add(terrainMesh)
    }

    // 水面（动态波纹着色器）
    const wSpan2 = (lon1 - lon0) * SCALE * Math.cos((cy * Math.PI) / 180)
    const hSpan2 = (lat0 - lat1) * SCALE
    // 告警联动：风暴潮警戒级 → 水面泛红警示
    const waterColA = alertLevel >= 2 ? 0x8a3a2a : 0x2a7ab8
    const waterColB = alertLevel >= 2 ? 0xd86a4a : 0x5ec8e8
    const waterMat = new THREE.ShaderMaterial({
      transparent: true,
      uniforms: {
        time: { value: 0 },
        colorA: { value: new THREE.Color(waterColA) },
        colorB: { value: new THREE.Color(waterColB) },
      },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `varying vec2 vUv; uniform float time; uniform vec3 colorA; uniform vec3 colorB;
        void main(){
          float w1 = sin(vUv.x * 40.0 + time * 1.2) * 0.5 + 0.5;
          float w2 = sin(vUv.y * 35.0 + time * 0.8 + 2.0) * 0.5 + 0.5;
          float w3 = sin((vUv.x + vUv.y) * 25.0 + time * 1.6) * 0.5 + 0.5;
          float wave = w1 * 0.4 + w2 * 0.35 + w3 * 0.25;
          vec3 col = mix(colorA, colorB, wave);
          gl_FragColor = vec4(col, 0.85); }`,
    })
    const waterMesh = new THREE.Mesh(new THREE.PlaneGeometry(wSpan2, hSpan2, 64, 64), waterMat)
    waterMesh.rotation.x = -Math.PI / 2
    waterMesh.position.y = alertLevel >= 2 ? 1.8 : 0.5 // 警戒级水位抬升示意
    scene.add(waterMesh)

    // 建筑（渐变色 + 阴影 + 超高层光柱）
    let buildingsMesh = null
    if (data.buildings?.length) {
      const bList = data.buildings
      const bGeo = new THREE.BoxGeometry(1, 1, 1)
      bGeo.translate(0, 0.5, 0)
      const bMat = new THREE.MeshStandardMaterial({
        color: 0xffffff, roughness: 0.35, metalness: 0.25,
        transparent: true, opacity: 0.96,
        emissive: 0x1a2436, emissiveIntensity: 0.5,
      })
      buildingsMesh = new THREE.InstancedMesh(bGeo, bMat, bList.length)
      buildingsMesh.castShadow = true
      buildingsMesh.receiveShadow = true
      const m4 = new THREE.Matrix4()
      const maxH = Math.max(...bList.map((b) => b.height_m), 1)
      bList.forEach((b, i) => {
        const [x, y] = toXY(b.lon, b.lat)
        const h = Math.max(b.height_m * 0.42, 2)
        const w = Math.max(3.0 - (b.height_m / maxH) * 1.6, 1.0)
        m4.makeScale(w, h, w)
        m4.setPosition(x, 0, -y)
        buildingsMesh.setMatrixAt(i, m4)
        const t = b.height_m / maxH
        let c
        if (t > 0.75) c = new THREE.Color().setHSL(0.11, 0.80, 0.72)
        else if (t > 0.4) c = new THREE.Color().setHSL(0.09, 0.35, 0.78)
        else c = new THREE.Color().setHSL(0.57, 0.30, 0.62)
        buildingsMesh.setColorAt(i, c)
      })
      if (buildingsMesh.instanceColor) buildingsMesh.instanceColor.needsUpdate = true
      scene.add(buildingsMesh)

      // 超高层地标光柱
      const landmarks = bList.filter(b => b.height_m > 250).slice(0, 12)
      landmarks.forEach((b) => {
        const [x, y] = toXY(b.lon, b.lat)
        const h = b.height_m * 0.42
        const beam = new THREE.Mesh(
          new THREE.CylinderGeometry(1.2, 2.4, 30, 8, 1, true),
          new THREE.MeshBasicMaterial({ color: 0x6db8ff, transparent: true, opacity: 0.4, side: THREE.DoubleSide }),
        )
        beam.position.set(x, h + 14, -y)
        scene.add(beam)
      })
    }

    // 灾种点（脉冲呼吸：内核球 + 扩散环）
    const pulsePoints = []
    const pointGroups = []
    if (data.points) {
      const mkPoints = (pts, color, size) => {
        if (!pts?.length) return null
        const group = new THREE.Group()
        pts.forEach((p, idx) => {
          const [x, y] = toXY(p.lon, p.lat)
          const core = new THREE.Mesh(
            new THREE.SphereGeometry(size * 0.45, 10, 10),
            new THREE.MeshBasicMaterial({ color }),
          )
          core.position.set(x, 3.5, -y)
          const ring = new THREE.Mesh(
            new THREE.RingGeometry(size * 0.6, size * 0.9, 20),
            new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5, side: THREE.DoubleSide }),
          )
          ring.rotation.x = -Math.PI / 2
          ring.position.set(x, 2.2, -y)
          group.add(core, ring)
          pulsePoints.push({ ring, phase: (idx * 0.7) % (Math.PI * 2) })
        })
        return group
      }
      const floodP = mkPoints(data.points.flood, 0xff9a3d, 2.4)
      const slideP = mkPoints(data.points.landslide, 0xff5e4d, 2.8)
      const marineP = mkPoints(data.points.marine, 0x3de8dc, 3.4)
      ;[floodP, slideP, marineP].forEach((m) => { if (m) { scene.add(m); pointGroups.push(m) } })
    }

    // 台风云带（螺旋 + 路径流光）
    let typhoonGroup = null, cloud = null, tubeMat = null
    if (typhoonTrack?.length > 1) {
      typhoonGroup = new THREE.Group()
      const pts3 = typhoonTrack.map((p) => {
        const [x, y] = toXY(p.lon, p.lat)
        return new THREE.Vector3(x, 14, -y)
      })
      const curve = new THREE.CatmullRomCurve3(pts3)
      const tubeGeo = new THREE.TubeGeometry(curve, 200, 1.4, 8, false)
      tubeMat = new THREE.ShaderMaterial({
        transparent: true,
        uniforms: { time: { value: 0 } },
        vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
        fragmentShader: `varying vec2 vUv; uniform float time;
          void main(){
            float flow = fract(vUv.x * 6.0 - time * 1.5);
            float glow = smoothstep(0.0, 0.35, flow) * smoothstep(0.7, 0.35, flow);
            vec3 col = mix(vec3(0.2, 0.5, 1.0), vec3(1.0, 0.9, 0.4), glow);
            gl_FragColor = vec4(col, 0.35 + glow * 0.65); }`,
      })
      typhoonGroup.add(new THREE.Mesh(tubeGeo, tubeMat))
      const cur = typhoonTrack[typhoonTrack.length - 1]
      const [tcx, tcy] = toXY(cur.lon, cur.lat)
      cloud = new THREE.Group()
      const cloudMat = new THREE.MeshBasicMaterial({ color: 0xdfe8ff, transparent: true, opacity: 0.22, side: THREE.DoubleSide })
      for (let arm = 0; arm < 4; arm++) {
        for (let s = 0; s < 14; s++) {
          const t = s / 14
          const ang = arm * (Math.PI / 2) + t * 2.6
          const r = 8 + t * 42
          const puff = new THREE.Mesh(new THREE.SphereGeometry(4.5 + t * 3.5, 8, 6), cloudMat)
          puff.position.set(Math.cos(ang) * r, 10 + Math.sin(t * 3) * 3, Math.sin(ang) * r)
          cloud.add(puff)
        }
      }
      cloud.position.set(tcx, 0, -tcy)
      typhoonGroup.add(cloud)
      const eye = new THREE.Mesh(
        new THREE.SphereGeometry(3.5, 16, 16),
        new THREE.MeshBasicMaterial({ color: 0xffffff }),
      )
      eye.position.set(tcx, 16, -tcy)
      typhoonGroup.add(eye)
      scene.add(typhoonGroup)
    }

    // 降雨粒子系统
    const N = 2200
    const rainGeo = new THREE.BufferGeometry()
    const rainPos = new Float32Array(N * 3)
    const rainVel = new Float32Array(N)
    for (let i = 0; i < N; i++) {
      rainPos[i * 3] = (Math.random() - 0.5) * wSpan2
      rainPos[i * 3 + 1] = Math.random() * 160 + 20
      rainPos[i * 3 + 2] = (Math.random() - 0.5) * hSpan2
      rainVel[i] = 1.6 + Math.random() * 2.2
    }
    rainGeo.setAttribute('position', new THREE.BufferAttribute(rainPos, 3))
    const rainSystem = new THREE.Points(rainGeo, new THREE.PointsMaterial({
      color: 0x9ec8ff, size: 1.6, transparent: true, opacity: 0.55, sizeAttenuation: true,
    }))
    scene.add(rainSystem)

    // 洪水演进
    const floodMat = new THREE.ShaderMaterial({
      transparent: true,
      uniforms: { time: { value: 0 }, level: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `varying vec2 vUv; uniform float time; uniform float level;
        void main(){
          if (level <= 0.01) discard;
          vec2 c = vUv - 0.5;
          float d = length(c) * 2.0;
          if (d > level) discard;
          float ring = sin(d * 30.0 - time * 3.0) * 0.5 + 0.5;
          float alpha = (1.0 - d / level) * 0.75 * (0.6 + ring * 0.4);
          vec3 col = mix(vec3(1.0, 0.55, 0.15), vec3(1.0, 0.85, 0.3), ring);
          gl_FragColor = vec4(col, alpha); }`,
    })
    const floodMesh = new THREE.Mesh(new THREE.PlaneGeometry(wSpan2 * 0.9, hSpan2 * 0.9, 1, 1), floodMat)
    floodMesh.rotation.x = -Math.PI / 2
    floodMesh.position.y = 2.5
    scene.add(floodMesh)

    // 相机控制（入场飞入 + 拖拽 + 滚轮）
    camera.position.set(0, 480, 700)
    camera.lookAt(0, 0, 0)
    let dragging = false, lastX = 0, lastY = 0
    let rotV = 0.0016
    let targetRotY = 0.3, curRotY = 0.3, dist = 700, targetDist = 320
    let pitch = 0.9, targetPitch = 0.9
    let flyInT = 0 // 0→1

    const onDown = (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY }
    const onMove = (e) => {
      if (!dragging) return
      targetRotY += (e.clientX - lastX) * 0.005
      targetPitch = Math.max(0.12, Math.min(1.5, targetPitch + (e.clientY - lastY) * 0.004))
      lastX = e.clientX; lastY = e.clientY
    }
    const onUp = () => { dragging = false }
    const onWheel = (e) => {
      e.preventDefault()
      targetDist = Math.max(60, Math.min(900, targetDist + e.deltaY * 0.35))
    }
    renderer.domElement.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false })

    // 引擎控制接口
    engineRef.current = {
      setLayers: (lyr) => {
        if (buildingsMesh) buildingsMesh.visible = !!lyr.buildings
        pointGroups.forEach((g) => { g.visible = !!lyr.points })
        if (typhoonGroup) typhoonGroup.visible = !!lyr.typhoon
        rainSystem.visible = !!lyr.rain
        floodMesh.visible = !!lyr.floodAnim
      },
      applyView: (v) => {
        const def = VIEWS.find(x => x.id === v) || VIEWS[0]
        targetPitch = def.pitch
        targetDist = def.dist
      },
    }

    // 渲染循环
    const clock = new THREE.Clock()
    let raf
    const animate = () => {
      raf = requestAnimationFrame(animate)
      const t = clock.getElapsedTime()

      waterMat.uniforms.time.value = t
      for (const p of pulsePoints) {
        const ph = (t * 1.4 + p.phase) % (Math.PI * 2)
        const s = 1 + Math.sin(ph) * 0.5
        p.ring.scale.setScalar(s)
        p.ring.material.opacity = 0.55 * (1 - Math.sin(ph) * 0.5)
      }
      if (cloud) cloud.rotation.y = t * 0.35
      if (tubeMat) tubeMat.uniforms.time.value = t

      if (rainSystem.visible) {
        const pa = rainSystem.geometry.attributes.position
        for (let i = 0; i < N; i++) {
          let y = pa.array[i * 3 + 1] - rainVel[i]
          if (y < 0) y = 160 + Math.random() * 30
          pa.array[i * 3 + 1] = y
        }
        pa.needsUpdate = true
      }
      if (floodMesh.visible) {
        const cycle = (t % 24) / 24
        const level = cycle < 0.15 ? (cycle / 0.15) * 0.3
                   : cycle < 0.75 ? 0.3 + ((cycle - 0.15) / 0.6) * 0.65
                   : 1.0 - ((cycle - 0.75) / 0.25)
        floodMat.uniforms.level.value = Math.max(0, level)
        floodMat.uniforms.time.value = t
      }

      // 相机
      if (flyInT < 1) {
        flyInT = Math.min(1, flyInT + 0.008)
        const e = 1 - Math.pow(1 - flyInT, 3)
        dist = 700 - 380 * e
        curRotY = 0.3 + 0.15 * e
      } else {
        if (!dragging) targetRotY += rotV
        curRotY += (targetRotY - curRotY) * 0.07
        pitch += (targetPitch - pitch) * 0.07
        dist += (targetDist - dist) * 0.07
      }
      const px = Math.sin(curRotY) * Math.cos(pitch) * dist
      const pz = Math.cos(curRotY) * Math.cos(pitch) * dist
      const py = Math.sin(pitch) * dist
      camera.position.set(px, py, pz)
      camera.lookAt(0, 0, 0)
      renderer.render(scene, camera)
    }
    animate()
    setStatus('')

    const onResize = () => {
      const w = mount.clientWidth || W
      if (w < 10) return // 布局未就绪
      camera.aspect = w / H
      camera.updateProjectionMatrix()
      renderer.setSize(w, H, false) // false = 不写 style（CSS 100% 控制显示尺寸）
    }
    window.addEventListener('resize', onResize)
    // ResizeObserver：容器自身尺寸变化（侧栏收起/布局变化）也触发
    const ro = new ResizeObserver(onResize)
    ro.observe(mount)
    // 首帧强制同步一次（确保布局完成后尺寸正确）
    requestAnimationFrame(onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      renderer.domElement.removeEventListener('mousedown', onDown)
      renderer.domElement.removeEventListener('wheel', onWheel)
      renderer.dispose()
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement)
    }
  }, [ready, typhoonTrack, height, alertLevel])

  // 图层/视角同步
  useEffect(() => {
    if (engineRef.current?.setLayers) engineRef.current.setLayers(layers)
  }, [layers, ready])
  useEffect(() => {
    if (engineRef.current?.applyView) engineRef.current.applyView(view)
  }, [view, ready])

  return (
    <div className="scene3d-wrap" style={{ position: 'relative' }}>
      {status && <div className="scene3d-status">{status}</div>}
      <div ref={mountRef} style={{ width: '100%', height: `${height}px`, borderRadius: '10px', overflow: 'hidden' }}>
        <style>{`.scene3d-wrap canvas { width: 100% !important; height: 100% !important; display: block; }`}</style>
      </div>

      {!status && (
        <>
          <div className="s3d-layers">
            <div className="s3d-layers-title">图层</div>
            {LAYER_DEFS.map((l) => (
              <button
                key={l.id}
                className={`s3d-layer-btn ${layers[l.id] ? 'on' : ''}`}
                onClick={() => setLayers((s) => ({ ...s, [l.id]: !s[l.id] }))}
                title={l.label}
              >
                <span>{l.icon}</span>
              </button>
            ))}
          </div>
          <div className="s3d-views">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                className={`s3d-view-btn ${view === v.id ? 'on' : ''}`}
                onClick={() => setView(v.id)}
              >
                {v.icon} {v.label}
              </button>
            ))}
          </div>
          <div className="scene3d-legend">
            <span><i style={{ background: '#ff9a3d' }} />内涝点</span>
            <span><i style={{ background: '#ff5e4d' }} />滑坡隐患</span>
            <span><i style={{ background: '#3de8dc' }} />潮位/波浪站</span>
            {layers.typhoon && <span><i style={{ background: '#4da3ff' }} />台风路径</span>}
            <span className="scene3d-hint">拖拽旋转 · 滚轮缩放</span>
            <span className="scene3d-src">DEM: Copernicus 30m · 建筑: OSM · 隐患点: 规自局/HKO/天地图</span>
          </div>
        </>
      )}
    </div>
  )
}
