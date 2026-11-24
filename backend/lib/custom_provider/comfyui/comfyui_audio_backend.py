"""Synthesize narration with a ComfyUI audio workflow."""

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from lib.backends.artifact_download_guard import artifact_http_client
from lib.backends.audio_backends.base import AudioCapability, AudioSynthesisResult, VoiceOption
from lib.infra.ffmpeg import ffmpeg_executable, local_file_input

from .comfyui_client import ComfyuiClient, client_id_for
from .comfyui_execution import ComfyuiExecution
from .node_pool import comfyui_node_urls, generation_node


_QWEN_PRESET = "FB_Qwen3TTSCustomVoice"
_QWEN_DESIGN = "FB_Qwen3TTSVoiceDesign"
_QWEN_SAMPLING_INPUTS = ("seed", "max_new_tokens", "top_p", "top_k", "temperature", "repetition_penalty", "attention")


class ComfyuiAudioBackend:
    @property
    def capabilities(self):
        capabilities = {AudioCapability.TEXT_TO_SPEECH}
        if any(
            target["input"] == "text" and self.definition["workflow"][target["node"]]["class_type"] == _QWEN_PRESET
            for target in self.definition["bindings"]["prompt"]
        ):
            capabilities.add(AudioCapability.VOICE_DESIGN)
        return capabilities

    def __init__(self, *, provider_id, model, base_url, api_key, definition, extra_base_urls: tuple[str, ...] = ()):
        self.name = provider_id
        self.model = model
        self.definition = definition
        self._api_key = api_key
        self._nodes = comfyui_node_urls(base_url, extra_base_urls)
        self.client = ComfyuiClient(base_url=base_url, api_key=api_key, definition=definition)
        self.execution = ComfyuiExecution(client=self.client, definition=definition, media_type="audio")

    def list_voices(self):
        if not any(node["class_type"] == _QWEN_PRESET for node in self.definition["workflow"].values()):
            return []
        return [VoiceOption(voice, voice) for voice in (
            "Aiden", "Dylan", "Eric", "Ono_anna", "Ryan", "Serena", "Sohee", "Uncle_fu", "Vivian",
        )]

    def _bind_prompt(self, request):
        workflow = deepcopy(self.definition["workflow"])
        if request.voice_design and (AudioCapability.VOICE_DESIGN not in self.capabilities or not request.instructions):
            raise ValueError("Voice design requires a Qwen3-TTS workflow and voice instructions")
        voices = {voice.id for voice in self.list_voices()}
        for target in self.definition["bindings"]["prompt"]:
            node = workflow[target["node"]]
            inputs = node["inputs"]
            inputs[target["input"]] = request.text
            if node["class_type"] != _QWEN_PRESET:
                continue
            inputs["language"] = "Auto"
            if request.voice_design and target["input"] == "text":
                node["class_type"] = _QWEN_DESIGN
                node["inputs"] = {
                    "text": request.text,
                    "instruct": request.instructions,
                    "model_choice": "1.7B",
                    "device": inputs["device"],
                    "precision": inputs["precision"],
                    "language": inputs["language"],
                    "unload_model_after_generate": inputs.get("unload_model_after_generate", False),
                    **{name: inputs[name] for name in _QWEN_SAMPLING_INPUTS if name in inputs},
                }
            elif request.voice in voices:
                inputs["speaker"] = request.voice
        return workflow

    async def synthesize(self, request):
        url = await generation_node(self.name, self._nodes, self._api_key, self.definition)
        if url is not None and url != self.client.base_url:
            return await ComfyuiAudioBackend(
                provider_id=self.name, model=self.model, base_url=url,
                api_key=self._api_key, definition=self.definition,
            ).synthesize(request)
        workflow = self._bind_prompt(request)

        with TemporaryDirectory(dir=request.output_path.parent) as temporary:
            source = Path(temporary) / "audio.flac"
            wav = Path(temporary) / "audio.wav"
            async with artifact_http_client(timeout=60, follow_redirects=True) as http:
                prompt_id = await self.client.submit_prompt(http, workflow, client_id=client_id_for(uuid4().hex))
                await self.execution.fetch_artifact(http, prompt_id, output_path=source, poll_timeout_seconds=300)
            process = await asyncio.create_subprocess_exec(
                ffmpeg_executable(), "-nostdin", "-loglevel", "error",
                *local_file_input(source), "-c:a", "pcm_s16le", str(wav),
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await process.communicate()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            if process.returncode:
                raise RuntimeError(f"ComfyUI FLAC conversion failed: {stderr.decode(errors='replace').strip()}")
            wav.replace(request.output_path)
        return AudioSynthesisResult(self.name, self.model, request.text, request.output_path)
