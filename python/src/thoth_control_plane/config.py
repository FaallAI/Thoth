"""Configuration for the Thoth control plane."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from thoth_control_plane.domain.prompt_proposals import PromptModelDefinition, SafeIdentifier


class PromptProviderRuntimeDefinition(BaseModel):
    """Worker/API shared runtime definition; base_url and credential stay server-side."""

    model_config = ConfigDict(extra="forbid", strict=True)

    provider_id: SafeIdentifier
    label: Annotated[str, Field(min_length=1, max_length=200)]
    protocol: Literal["openai_compatible"]
    base_url: AnyHttpUrl
    credential_id: SafeIdentifier
    models: tuple[PromptModelDefinition, ...]
    enabled: bool = True

    @field_validator("models", mode="before")
    @classmethod
    def _coerce_models(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class SettingsValidationError(ValueError):
    """Safe settings validation error that does not retain constructor inputs."""

    def errors(self) -> list[dict[str, str]]:
        """Provide a Pydantic-like sanitized error shape without input values."""

        return [{"type": "value_error", "msg": str(self)}]


def _is_same_origin_path(value: str) -> bool:
    """A preview URL must stay same-origin so no capability can travel to another host."""
    return (
        value.startswith("/")
        and not value.startswith("//")
        and not any(character in value for character in ":\\?#")
    )


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or explicit values."""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)

    THOTH_CONTROL_PLANE_API_KEY: SecretStr
    THOTH_CONTROL_PLANE_CORS_ORIGINS: list[str] = Field(default_factory=list)
    THOTH_CONTROL_PLANE_ARTIFACT_ROOT: Path = Path(".thoth-artifacts")
    THOTH_FFPROBE: str = "ffprobe"
    THOTH_TEMPORAL_TARGET: str = "localhost:7233"
    THOTH_TEMPORAL_NAMESPACE: str = "default"
    THOTH_EDITOR_DATABASE_URL: SecretStr | None = None
    THOTH_EDITOR_PREVIEW_SIGNING_KEY: SecretStr | None = None
    THOTH_EDITOR_PREVIEW_TTL_SECONDS: Annotated[int, Field(ge=30, le=3600)] = 300
    THOTH_EDITOR_PREVIEW_BASE_URL: str | None = None
    THOTH_SITE_ORIGIN: str = "http://localhost:8088"
    THOTH_AUTH_SECRET: SecretStr | None = None
    THOTH_AUTH_GOOGLE_CLIENT_ID: str | None = None
    THOTH_AUTH_GOOGLE_CLIENT_SECRET: SecretStr | None = None
    THOTH_AUTH_GOOGLE_DOMAIN: str | None = None
    THOTH_AUTH_GITHUB_CLIENT_ID: str | None = None
    THOTH_AUTH_GITHUB_CLIENT_SECRET: SecretStr | None = None
    THOTH_AUTH_GITHUB_ORG: str | None = None
    THOTH_SMTP_HOST: str | None = None
    THOTH_SMTP_PORT: Annotated[int, Field(ge=1, le=65535)] = 587
    THOTH_SMTP_USERNAME: str | None = None
    THOTH_SMTP_PASSWORD: SecretStr | None = None
    THOTH_SMTP_FROM: str | None = None
    THOTH_AUTH_WORKSPACE_TOKENS: bool = False
    # Admit verified users outside the Google domain / GitHub org (billing spec 3.2).
    THOTH_AUTH_PUBLIC_SIGNUP: bool = False
    # Billing (spec 2026-10-20): both empty leave checkout and the webhook off.
    THOTH_XENDIT_SECRET_KEY: SecretStr | None = None
    THOTH_XENDIT_CALLBACK_TOKEN: SecretStr | None = None
    THOTH_PROMPT_PROVIDER_CATALOG: tuple[PromptProviderRuntimeDefinition, ...] = ()
    THOTH_PROMPT_PROVIDER_SECRETS: dict[SafeIdentifier, SecretStr] = Field(default_factory=dict)
    THOTH_RENDERER_INTERNAL_URL: AnyHttpUrl | None = None
    THOTH_RENDERER_INTERNAL_CREDENTIAL: SecretStr | None = None
    THOTH_RENDER_MAX_SECONDS: Annotated[int, Field(ge=60, le=7200)] = 900
    THOTH_RENDERER_VERSION: str = "remotion-4.0.538"
    THOTH_RENDER_PRESET_ID: Literal["standard_vertical_mp4_v1"] = "standard_vertical_mp4_v1"
    # A Fernet key; source accounts need it and the editor database, else they stay off.
    THOTH_ACCOUNT_VAULT_KEY: SecretStr | None = None
    # Spec 2026-10-13, 3.2: sealed per-account browser profiles, a volume of their own.
    THOTH_ACCOUNT_PROFILE_DIR: Path = Path("/var/lib/thoth/account-profiles")
    # Stage 4 source attribution. Without a key, that half of the evidence is skipped.
    THOTH_FFMPEG: str = "ffmpeg"
    THOTH_SOURCE_VISION_MODEL: str = "qwen/qwen3-vl-30b-a3b-instruct"
    # Vision and Jev decisions both go through OpenRouter (operator, 2026-10-08/09).
    THOTH_OPENROUTER_API_KEY: SecretStr | None = None
    # Voice adapter (spec 2026-10-18, section 9): ElevenLabs, or any OpenAI-compatible server.
    THOTH_ELEVENLABS_API_KEY: SecretStr | None = None
    THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL: AnyHttpUrl | None = None
    THOTH_VOICE_OPENAI_COMPATIBLE_API_KEY: SecretStr | None = None
    # Read by the API when it starts an identify_original workflow; a kill switch.
    THOTH_SOURCE_ATTRIBUTION_ENABLED: bool = True
    # Speech models baked into the image (spec 2026-10-13); never downloaded at run time.
    THOTH_WHISPER_MODEL_DIR: Path = Path("/opt/thoth/models/whisper-large-v3-turbo")
    THOTH_DIARIZATION_MODEL_DIR: Path = Path("/opt/thoth/models/diarization")
    THOTH_EMBEDDING_MODEL_DIR: Path = Path("/opt/thoth/models/embedding")
    # Stage 5a content assembly. Off by default; the worker refuses to start with it on and
    # no ffmpeg or ffprobe (operator, 2026-10-11).
    THOTH_CONTENT_ASSEMBLY_ENABLED: bool = False
    THOTH_FOOTAGE_ENABLED: bool = False
    THOTH_FOOTAGE_STORY_MIN: Annotated[float, Field(ge=0.0, le=1.0)] = 0.36
    THOTH_SUBTITLE_OCR_MAX_FRAMES: Annotated[int, Field(ge=1, le=60)] = 12
    THOTH_FIGURES_MODEL: str = "deepseek/deepseek-v4-flash-0731"
    THOTH_FOOTAGE_QUERY_MODEL: str = "deepseek/deepseek-v4-flash-0731"
    # Where activities stage media for ffmpeg and the models; None is the system temp directory.
    THOTH_MEDIA_SCRATCH_DIR: Path | None = None
    # Workflow media in S3-compatible storage (spec 2026-10-17); unset keeps it on the volume.
    THOTH_MEDIA_S3_ENDPOINT: str | None = None
    THOTH_MEDIA_S3_BUCKET: str = "thoth-media"
    THOTH_MEDIA_S3_ACCESS_KEY: SecretStr | None = None
    THOTH_MEDIA_S3_SECRET_KEY: SecretStr | None = None
    THOTH_MEDIA_S3_SECURE: bool = False
    #: Signing a probe URL locally needs the region; MinIO's own default is us-east-1.
    THOTH_MEDIA_S3_REGION: str = "us-east-1"
    # The hourly sweep of unregistered uploads only logs what it finds until the operator
    # turns deletion on: MinIO holds the only copy of every upload.
    THOTH_UPLOAD_SWEEP_DELETE: bool = False

    def __init__(self, **values: object) -> None:
        """Load settings, then reject incomplete pairs without retaining inputs."""
        super().__init__(**values)
        preview_base_url = self.THOTH_EDITOR_PREVIEW_BASE_URL
        if preview_base_url is not None and not _is_same_origin_path(preview_base_url):
            raise SettingsValidationError(
                "editor preview base URL must be a same-origin relative path"
            )
        has_renderer_url = self.THOTH_RENDERER_INTERNAL_URL is not None
        has_renderer_credential = bool(
            self.THOTH_RENDERER_INTERNAL_CREDENTIAL is not None
            and self.THOTH_RENDERER_INTERNAL_CREDENTIAL.get_secret_value().strip()
        )
        if has_renderer_url != has_renderer_credential:
            raise SettingsValidationError(
                "renderer internal URL and credential must be configured together"
            )
        provider_ids: set[str] = set()
        for provider in self.THOTH_PROMPT_PROVIDER_CATALOG:
            if provider.provider_id in provider_ids:
                raise SettingsValidationError("prompt provider catalog contains a duplicate id")
            provider_ids.add(provider.provider_id)
            model_ids: set[str] = set()
            for model in provider.models:
                if model.model_id in model_ids:
                    raise SettingsValidationError(
                        "prompt provider catalog contains a duplicate model id"
                    )
                model_ids.add(model.model_id)

    @field_validator(
        "THOTH_AUTH_SECRET",
        "THOTH_AUTH_GOOGLE_CLIENT_ID",
        "THOTH_AUTH_GOOGLE_CLIENT_SECRET",
        "THOTH_AUTH_GOOGLE_DOMAIN",
        "THOTH_AUTH_GITHUB_CLIENT_ID",
        "THOTH_AUTH_GITHUB_CLIENT_SECRET",
        "THOTH_AUTH_GITHUB_ORG",
        "THOTH_SMTP_HOST",
        "THOTH_SMTP_USERNAME",
        "THOTH_SMTP_PASSWORD",
        "THOTH_SMTP_FROM",
        "THOTH_XENDIT_SECRET_KEY",
        "THOTH_XENDIT_CALLBACK_TOKEN",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Compose passes `${VAR:-}` as an empty string; empty means not configured."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("THOTH_SITE_ORIGIN")
    @classmethod
    def _origin(cls, value: str) -> str:
        """Compared exactly with the browser's Origin header, so keep only scheme://host[:port]."""
        scheme, _, rest = value.strip().partition("://")
        return f"{scheme.lower()}://{rest.split('/', 1)[0].lower()}"

    @property
    def cookie_secure(self) -> bool:
        return self.THOTH_SITE_ORIGIN.startswith("https://")

    @property
    def email_codes_enabled(self) -> bool:
        return self.THOTH_SMTP_HOST is not None and self.THOTH_SMTP_FROM is not None

    @property
    def sign_in_ready(self) -> bool:
        """Everything a provider needs besides its own client: a secret, the DB, and mail."""
        return (
            self.THOTH_AUTH_SECRET is not None
            and self.THOTH_EDITOR_DATABASE_URL is not None
            and self.email_codes_enabled
        )

    @property
    def google_sign_in_enabled(self) -> bool:
        # Public sign-up ignores the domain rule, so it does not need a domain (billing 3.2).
        return self.sign_in_ready and None not in (
            self.THOTH_AUTH_GOOGLE_CLIENT_ID,
            self.THOTH_AUTH_GOOGLE_CLIENT_SECRET,
            "public" if self.THOTH_AUTH_PUBLIC_SIGNUP else self.THOTH_AUTH_GOOGLE_DOMAIN,
        )

    @property
    def github_sign_in_enabled(self) -> bool:
        return self.sign_in_ready and None not in (
            self.THOTH_AUTH_GITHUB_CLIENT_ID,
            self.THOTH_AUTH_GITHUB_CLIENT_SECRET,
            "public" if self.THOTH_AUTH_PUBLIC_SIGNUP else self.THOTH_AUTH_GITHUB_ORG,
        )

    @property
    def billing_enabled(self) -> bool:
        return (
            self.THOTH_XENDIT_SECRET_KEY is not None
            and self.THOTH_XENDIT_CALLBACK_TOKEN is not None
            and self.THOTH_EDITOR_DATABASE_URL is not None
        )

    @property
    def prompt_provider_secrets(self) -> dict[str, SecretStr]:
        """Worker-only credential map keyed by catalog credential_id."""
        return dict(self.THOTH_PROMPT_PROVIDER_SECRETS)

    @property
    def account_vault_key(self) -> str | None:
        """The source-account vault key, when the editor database is configured too."""
        if self.THOTH_ACCOUNT_VAULT_KEY is None or self.THOTH_EDITOR_DATABASE_URL is None:
            return None
        return self.THOTH_ACCOUNT_VAULT_KEY.get_secret_value().strip() or None

    @property
    def openrouter_api_key(self) -> str | None:
        """The OpenRouter key for vision and Jev; attribution refuses to start without it."""
        return _secret(self.THOTH_OPENROUTER_API_KEY)

    @property
    def renderer_enabled(self) -> bool:
        """Whether a private renderer is fully configured; absence only degrades."""
        return (
            self.THOTH_RENDERER_INTERNAL_URL is not None
            and self.THOTH_RENDERER_INTERNAL_CREDENTIAL is not None
        )


def _secret(value: SecretStr | None) -> str | None:
    return (value.get_secret_value().strip() or None) if value is not None else None
