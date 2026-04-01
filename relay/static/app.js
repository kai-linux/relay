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
        };

        this.els.btn.addEventListener("click", () => this.onButtonPress());
    }

    async init() {
        // Check for secure context (HTTPS or localhost)
        if (!window.isSecureContext) {
            this.showError(
                "HTTPS required for microphone access.\n" +
                "Access this page over https:// or localhost."
            );
            return;
        }

        // Check for mediaDevices support
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.showError("This browser doesn't support audio recording.");
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true },
            });
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: this.pickMimeType(),
            });
            this.mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) this.audioChunks.push(e.data);
            };
            this.mediaRecorder.onstop = () => this.sendAudio();
            this.setState("ready");
        } catch (err) {
            if (err.name === "NotAllowedError") {
                this.showError("Microphone permission denied.\nAllow access and reload.");
            } else {
                this.showError("Could not access microphone:\n" + err.message);
            }
        }
    }

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
        } catch {
            this.addMessage("error", "Connection failed. Is the server running?");
            this.setState("ready");
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
            buffer = lines.pop(); // keep incomplete line in buffer

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
                        // Response audio chunk — interrupt status clips on first chunk
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

        // Stream ended — if we got response audio, make sure it plays out
        if (!this.receivedResponseAudio && this.state !== "speaking") {
            this.setState("ready");
        }
    }

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

        switch (state) {
            case "ready":
                this.els.iconMic.classList.remove("hidden");
                this.els.btn.classList.add("bg-zinc-800", "border-2", "border-zinc-700");
                this.els.status.textContent = "Tap to speak";
                break;
            case "recording":
                this.els.iconStop.classList.remove("hidden");
                this.els.pulse.classList.remove("hidden");
                this.els.btn.classList.add("bg-red-600", "border-2", "border-red-500");
                this.els.status.textContent = "Listening... tap to send";
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
    }
});
