/**
 * relay — voice client
 *
 * Handles audio recording, server communication, and response playback.
 * Designed for mobile walk-and-talk usage.
 */

class RelayClient {
    constructor() {
        this.sessionId = crypto.randomUUID();
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.currentAudio = null;
        this.state = "init"; // init | ready | recording | processing | speaking

        this.els = {
            btn: document.getElementById("record-btn"),
            status: document.getElementById("status"),
            transcript: document.getElementById("transcript"),
            emptyState: document.getElementById("empty-state"),
            pulse: document.getElementById("pulse"),
            iconMic: document.getElementById("icon-mic"),
            iconStop: document.getElementById("icon-stop"),
            iconSpinner: document.getElementById("icon-spinner"),
            iconSpeaking: document.getElementById("icon-speaking"),
        };

        this.els.btn.addEventListener("click", () => this.onButtonPress());
    }

    async init() {
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
        } catch {
            this.setState("ready");
            this.els.status.textContent = "Microphone access needed";
        }
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
        if (!this.mediaRecorder) {
            this.els.status.textContent = "Microphone access needed";
            return;
        }
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
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }
        this.setState("ready");
    }

    async sendAudio() {
        const mimeType = this.mediaRecorder.mimeType || "audio/webm";
        const blob = new Blob(this.audioChunks, { type: mimeType });

        // Skip very short recordings (likely accidental taps)
        if (blob.size < 1000) {
            this.setState("ready");
            return;
        }

        const ext = mimeType.includes("mp4") ? "mp4" : "webm";
        const form = new FormData();
        form.append("audio", blob, `recording.${ext}`);
        form.append("session_id", this.sessionId);

        try {
            const res = await fetch("/api/relay", { method: "POST", body: form });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this.addMessage("error", err.error || `Server error (${res.status})`);
                this.setState("ready");
                return;
            }

            const data = await res.json();

            if (data.error) {
                this.addMessage("error", data.error);
                this.setState("ready");
                return;
            }

            // Show transcript
            if (data.transcript) {
                this.addMessage("user", data.transcript);
            }
            if (data.response) {
                this.addMessage("assistant", data.response);
            }

            // Play response audio
            if (data.audio_base64) {
                this.playAudio(data.audio_base64);
            } else {
                this.setState("ready");
            }
        } catch {
            this.addMessage("error", "Connection failed. Is the server running?");
            this.setState("ready");
        }
    }

    playAudio(base64Data) {
        this.setState("speaking");
        const audio = new Audio(`data:audio/mp3;base64,${base64Data}`);
        this.currentAudio = audio;
        audio.onended = () => {
            this.currentAudio = null;
            this.setState("ready");
        };
        audio.onerror = () => {
            this.currentAudio = null;
            this.setState("ready");
        };
        audio.play().catch(() => {
            // Autoplay blocked — user will need to tap again
            this.currentAudio = null;
            this.setState("ready");
        });
    }

    addMessage(role, text) {
        // Remove empty state on first message
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

        // Reset all icons
        this.els.iconMic.classList.add("hidden");
        this.els.iconStop.classList.add("hidden");
        this.els.iconSpinner.classList.add("hidden");
        this.els.iconSpeaking.classList.add("hidden");
        this.els.pulse.classList.add("hidden");

        // Reset button style
        this.els.btn.className =
            "relative w-20 h-20 rounded-full flex items-center justify-center transition-all duration-200 active:scale-95 focus:outline-none";

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

// Boot
document.addEventListener("DOMContentLoaded", () => {
    const relay = new RelayClient();
    relay.init();

    // Request wake lock to prevent screen dimming during use
    if ("wakeLock" in navigator) {
        navigator.wakeLock.request("screen").catch(() => {});
    }
});
