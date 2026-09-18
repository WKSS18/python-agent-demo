# WebRTC / Electron / React Native 交付方案

## WebRTC 语音笔记

第一版已实现“双人笔记语音复盘房”：`POST /notes/{note_id}/voice-room` 创建房间，`WebSocket /voice-rooms/{room_id}/signal` 交换 offer/answer/ICE，浏览器通过 `RTCPeerConnection` 传输纯音频。音频不经过后端，FastAPI 只负责信令。

实时版本的接口边界：

```text
WebSocket signaling -> RTCPeerConnection -> coturn/LiveKit
                    -> ASR partial transcript
                    -> RAG query -> LLM SSE/WebRTC data channel
                    -> optional TTS audio track
```

上线前必须补：HTTPS、麦克风权限、ICE restart、TURN 中继、断线重连、音频时长/费用限制和录音删除策略。不要把模型密钥放在浏览器。

## Electron 桌面端

- Main：窗口、系统托盘、全局快捷键、文件选择和自动更新。
- Renderer：复用现有 React 页面。
- Preload：仅通过 `contextBridge` 暴露 `selectFile/saveDraft/quickCapture` 白名单。
- 安全配置：`nodeIntegration=false`、`contextIsolation=true`、启用 CSP。
- 个人知识库场景：快捷键收集剪贴板、离线草稿、Markdown 文件导入、联网后同步。

## React Native 移动端

- 本地 SQLite 保存离线草稿和上传队列。
- Keychain/Keystore 保存 Refresh Token，不使用明文 AsyncStorage。
- 图片压缩、断点上传、网络恢复重试。
- 通过现有 REST/SSE 接入笔记、复盘和 RAG；拍照 OCR 与录音转写复用后端异步导入。
- 大列表使用 FlatList，动画和重计算避免阻塞 JS 线程。

## 当前交付边界

当前 WebRTC 双人纯音频房已并入主项目；实时媒体服务器、录音转写、Electron 安装包和 RN 原生工程尚未直接并入。公网麦克风需要 HTTPS，房间目前是单进程内存状态，生产扩展时应加入 Redis 房间状态、TURN/coturn、断线重连和审计策略。
