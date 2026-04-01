/**
 * relay — voice client
 */

class RelayClient {
    constructor() {
        this.sessionId = crypto.randomUUID();
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.currentAudio = null;
        this.state = "init";
        this.handsFree = false;
        this.vad = null;
        this._keepAliveAudio = null;
        this._keepAliveCtx = null;

        this.els = {
            btn: document.getElementById("record-btn"),
            status: document.getElementById("status"),
            transcript: document.getElementById("transcript"),
            emptyState: document.getElementById("empty-state"),
            emptyText: document.getElementById("empty-text"),
            pulse: document.getElementById("pulse"),
            iconMic: document.getElementById("icon-mic"),
            iconStop: document.getElementById("icon-stop"),
            iconSpinner: document.getElementById("icon-spinner"),
            iconSpeaking: document.getElementById("icon-speaking"),
            modeToggle: document.getElementById("mode-toggle"),
            modeLabel: document.getElementById("mode-label"),
        };

        this.els.btn.addEventListener("click", () => this.onButtonPress());
        if (this.els.modeToggle) {
            this.els.modeToggle.addEventListener("change", () => this.toggleMode());
        }
    }

    async init() {
        if (!window.isSecureContext) {
            this.showError(
                "HTTPS required for microphone access.\n" +
                "Access this page over https:// or localhost."
            );
            return;
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.showError("This browser doesn't support audio recording.");
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true },
            });
            this.stream = stream;
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: this.pickMimeType(),
            });
            this.mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) this.audioChunks.push(e.data);
            };
            this.mediaRecorder.onstop = () => this.sendAudio();
            this.setupMediaSession();
            this.setupKeepAlive();
            this.setState("ready");
        } catch (err) {
            if (err.name === "NotAllowedError") {
                this.showError("Microphone permission denied.\nAllow access and reload.");
            } else {
                this.showError("Could not access microphone:\n" + err.message);
            }
        }
    }

    // ── Mode toggle ──────────────────────────────────────────────

    async toggleMode() {
        this.handsFree = this.els.modeToggle.checked;
        if (this.els.modeLabel) {
            this.els.modeLabel.textContent = this.handsFree ? "hands-free" : "push to talk";
        }

        if (this.handsFree) {
            await this.startVAD();
        } else {
            this.stopVAD();
            if (this.state === "ready" || this.state === "recording") {
                this.setState("ready");
            }
        }
    }

    // ── VAD (voice activity detection) ───────────────────────────

    async startVAD() {
        if (this.vad) return;

        // @ricky0123/vad-web loaded via CDN in index.html
        if (typeof vad === "undefined" || !vad.MicVAD) {
            console.warn("VAD library not loaded, hands-free unavailable");
            this.handsFree = false;
            this.els.modeToggle.checked = false;
            if (this.els.modeLabel) this.els.modeLabel.textContent = "push to talk";
            return;
        }

        try {
            this.vad = await vad.MicVAD.new({
                stream: this.stream,
                onSpeechStart: () => {
                    if (!this.handsFree) return;
                    // Only start recording if we're in a ready state
                    if (this.state === "ready") {
                        this.startRecording();
                    }
                },
                onSpeechEnd: (audio) => {
                    if (!this.handsFree) return;
                    if (this.state === "recording") {
                        this.stopRecording();
                    }
                },
                // Tuning: require a bit of silence before triggering end
                minSpeechFrames: 5,
                redemptionFrames: 15,
            });
            this.vad.start();
            this.setState("ready");
        } catch (err) {
            console.error("VAD init failed:", err);
            this.handsFree = false;
            this.els.modeToggle.checked = false;
            if (this.els.modeLabel) this.els.modeLabel.textContent = "push to talk";
        }
    }

    stopVAD() {
        if (this.vad) {
            this.vad.pause();
            this.vad.destroy();
            this.vad = null;
        }
    }

    // ── Headphone button (MediaSession API) ──────────────────────

    setupMediaSession() {
        if (!("mediaSession" in navigator)) return;

        // Play/pause actions map to push-to-talk toggle
        const toggle = () => this.onButtonPress();
        navigator.mediaSession.setActionHandler("play", toggle);
        navigator.mediaSession.setActionHandler("pause", toggle);
        // Some headphones send "stop" on long-press
        navigator.mediaSession.setActionHandler("stop", toggle);

        navigator.mediaSession.metadata = new MediaMetadata({
            title: "relay",
            artist: "Listening",
        });
    }

    // ── Background keep-alive ────────────────────────────────────

    setupKeepAlive() {
        // Play a silent audio loop to prevent iOS/Android from suspending
        // the tab when it's in the background or screen is off.
        document.addEventListener("visibilitychange", () => {
            if (document.hidden) {
                this._startKeepAlive();
            } else {
                this._stopKeepAlive();
            }
        });
    }

    _startKeepAlive() {
        if (this._keepAliveCtx) return;
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            // Generate a tiny silent buffer
            const buf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.loop = true;
            src.connect(ctx.destination);
            src.start();
            this._keepAliveCtx = ctx;
            this._keepAliveSrc = src;
        } catch {
            // Non-critical — best-effort keep-alive
        }
    }

    _stopKeepAlive() {
        if (this._keepAliveSrc) {
            try { this._keepAliveSrc.stop(); } catch {}
            this._keepAliveSrc = null;
        }
        if (this._keepAliveCtx) {
            try { this._keepAliveCtx.close(); } catch {}
            this._keepAliveCtx = null;
        }
    }

    // ── Core recording / playback ────────────────────────────────

    showError(msg) {
        this.els.emptyText.textContent = msg;
        this.els.emptyText.classList.remove("text-zinc-600");
        this.els.emptyText.classList.add("text-red-400");
        this.els.status.textContent = "";
        this.els.btn.disabled = true;
        this.els.btn.classList.add("opacity-30");
    }

    pickMimeType() {
        const types = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/mp4",
            "audio/ogg;codecs=opus",
        ];
        return types.find((t) => MediaRecorder.isTypeSupported(t)) || "";
    }

    onButtonPress() {
        switch (this.state) {
            case "ready":
                this.startRecording();
                break;
            case "recording":
                this.stopRecording();
                break;
            case "speaking":
                this.stopPlayback();
                break;
        }
    }

    startRecording() {
        if (!this.mediaRecorder) return;
        this.audioChunks = [];
        this.mediaRecorder.start();
        this.setState("recording");
    }

    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state === "recording") {
            this.mediaRecorder.stop();
            this.setState("processing");
        }
    }

    stopPlayback() {
        this.responseQueue = [];
        this.statusQueue = [];
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }
        if (this.currentStatusAudio) {
            this.currentStatusAudio.pause();
            this.currentStatusAudio = null;
        }
        this.setState("ready");
    }

    async sendAudio() {
        const mimeType = this.mediaRecorder.mimeType || "audio/webm";
        const blob = new Blob(this.audioChunks, { type: mimeType });

        if (blob.size < 1000) {
            this.setState("ready");
            return;
        }

        const ext = mimeType.includes("mp4") ? "mp4" : "webm";
        const form = new FormData();
        form.append("audio", blob, `recording.${ext}`);
        form.append("session_id", this.sessionId);

        try {
            const res = await fetch("/api/relay", {
                method: "POST",
                body: form,
                headers: { Accept: "text/event-stream" },
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this.addMessage("error", err.error || `Server error (${res.status})`);
                this.setState("ready");
                return;
            }

            await this.handleStream(res);
        } catch (err) {
            // Browser aborts fetch when app is backgrounded / switched —
            // not a real server failure, just silently reset.
            if (err.name === "AbortError" || err.name === "TypeError") {
                this.setState("ready");
            } else {
                this.addMessage("error", "Connection lost. Tap to try again.");
                this.setState("ready");
            }
        }
    }

    async handleStream(res) {
        this.receivedResponseAudio = false;
        this.responseQueue = [];
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.trim()) continue;
                let event;
                try {
                    event = JSON.parse(line);
                } catch {
                    continue;
                }

                switch (event.event) {
                    case "status":
                        this.els.status.textContent = event.text || "Working...";
                        break;
                    case "status_audio":
                        this.els.status.textContent = event.text || "Working...";
                        if (event.audio_base64) {
                            this.queueStatusClip(event.audio_base64);
                        }
                        break;
                    case "transcript":
                        this.addMessage("user", event.text);
                        break;
                    case "response":
                        this.addMessage("assistant", event.text);
                        break;
                    case "audio":
                        if (!this.receivedResponseAudio) {
                            this.receivedResponseAudio = true;
                            this.statusQueue = [];
                            if (this.currentStatusAudio) {
                                this.currentStatusAudio.pause();
                                this.currentStatusAudio = null;
                            }
                        }
                        this.queueResponseClip(event.audio_base64);
                        break;
                    case "error":
                        this.addMessage("error", event.text);
                        this.setState("ready");
                        return;
                }
            }
        }

        if (!this.receivedResponseAudio && this.state !== "speaking") {
            this.setState("ready");
        }
    }

    // ── Audio queue: status clips ────────────────────────────────

    queueStatusClip(base64Data) {
        if (!this.statusQueue) this.statusQueue = [];
        this.statusQueue.push(base64Data);
        if (!this.currentStatusAudio) this.playNextStatusClip();
    }

    playNextStatusClip() {
        if (!this.statusQueue || this.statusQueue.length === 0) {
            this.currentStatusAudio = null;
            return;
        }
        const clip = this.statusQueue.shift();
        const audio = new Audio(`data:audio/mp3;base64,${clip}`);
        this.currentStatusAudio = audio;
        audio.onended = () => this.playNextStatusClip();
        audio.onerror = () => this.playNextStatusClip();
        audio.play().catch(() => this.playNextStatusClip());
    }

    // ── Audio queue: response clips ──────────────────────────────

    queueResponseClip(base64Data) {
        if (!this.responseQueue) this.responseQueue = [];
        this.responseQueue.push(base64Data);
        if (!this.currentAudio) this.playNextResponseClip();
    }

    playNextResponseClip() {
        if (!this.responseQueue || this.responseQueue.length === 0) {
            this.currentAudio = null;
            this.setState("ready");
            return;
        }
        this.setState("speaking");
        const clip = this.responseQueue.shift();
        const audio = new Audio(`data:audio/mp3;base64,${clip}`);
        this.currentAudio = audio;
        audio.onended = () => this.playNextResponseClip();
        audio.onerror = () => this.playNextResponseClip();
        audio.play().catch(() => this.playNextResponseClip());
    }

    playAudio(base64Data) {
        this.queueResponseClip(base64Data);
    }

    // ── UI ───────────────────────────────────────────────────────

    addMessage(role, text) {
        if (this.els.emptyState) {
            this.els.emptyState.remove();
            this.els.emptyState = null;
        }

        const wrapper = document.createElement("div");
        wrapper.className = "space-y-1";

        if (role === "user") {
            const label = document.createElement("p");
            label.className = "text-xs text-zinc-600 uppercase tracking-wider";
            label.textContent = "you";
            wrapper.appendChild(label);

            const msg = document.createElement("p");
            msg.className = "text-zinc-400 text-sm";
            msg.textContent = text;
            wrapper.appendChild(msg);
        } else if (role === "assistant") {
            const label = document.createElement("p");
            label.className = "text-xs text-zinc-600 uppercase tracking-wider";
            label.textContent = "relay";
            wrapper.appendChild(label);

            const msg = document.createElement("p");
            msg.className = "text-white text-sm leading-relaxed";
            msg.textContent = text;
            wrapper.appendChild(msg);
        } else {
            const msg = document.createElement("p");
            msg.className = "text-red-400 text-sm";
            msg.textContent = text;
            wrapper.appendChild(msg);
        }

        this.els.transcript.appendChild(wrapper);
        this.els.transcript.scrollTop = this.els.transcript.scrollHeight;
    }

    setState(state) {
        this.state = state;

        this.els.iconMic.classList.add("hidden");
        this.els.iconStop.classList.add("hidden");
        this.els.iconSpinner.classList.add("hidden");
        this.els.iconSpeaking.classList.add("hidden");
        this.els.pulse.classList.add("hidden");

        this.els.btn.className =
            "relative w-24 h-24 rounded-full flex items-center justify-center transition-all duration-200 active:scale-95 focus:outline-none";

        const modePrefix = this.handsFree ? "Hands-free" : "";

        switch (state) {
            case "ready":
                this.els.iconMic.classList.remove("hidden");
                this.els.btn.classList.add("bg-zinc-800", "border-2", "border-zinc-700");
                this.els.status.textContent = this.handsFree
                    ? "Listening... just speak"
                    : "Tap to speak";
                break;
            case "recording":
                this.els.iconStop.classList.remove("hidden");
                this.els.pulse.classList.remove("hidden");
                this.els.btn.classList.add("bg-red-600", "border-2", "border-red-500");
                this.els.status.textContent = this.handsFree
                    ? "Hearing you..."
                    : "Listening... tap to send";
                break;
            case "processing":
                this.els.iconSpinner.classList.remove("hidden");
                this.els.btn.classList.add("bg-zinc-800", "border-2", "border-zinc-700");
                this.els.status.textContent = "Thinking...";
                break;
            case "speaking":
                this.els.iconSpeaking.classList.remove("hidden");
                this.els.btn.classList.add("bg-zinc-800", "border-2", "border-zinc-700");
                this.els.status.textContent = "Speaking... tap to stop";
                break;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const relay = new RelayClient();
    relay.init();

    if ("wakeLock" in navigator) {
        navigator.wakeLock.request("screen").catch(() => {});
        // Re-acquire wake lock when tab becomes visible again
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden && "wakeLock" in navigator) {
                navigator.wakeLock.request("screen").catch(() => {});
            }
        });
    }
});
