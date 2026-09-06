from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SinkResult:
    plugin_name: str
    status: str  # "OK", "SKIPPED", "ERROR"
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


class DocumentSinkPlugin(ABC):
    """Abstract interface for external tracking and document sinks (Notion, Drive, S3, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (e.g. 'notion', 'gdrive')."""
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True if the plugin is configured and active."""
        pass

    @abstractmethod
    def on_application_saved(
        self,
        user_id: str,
        application_id: str,
        application_data: dict[str, Any],
        version_data: dict[str, Any],
        files: dict[str, bytes] | None = None,
    ) -> SinkResult:
        """Executed when an application version is published or updated."""
        pass

    @abstractmethod
    def on_application_deleted(
        self,
        user_id: str,
        application_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SinkResult:
        """Executed when an application is deleted or archived."""
        pass


class PluginRegistry:
    """Registry managing available integration plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, DocumentSinkPlugin] = {}

    def register(self, plugin: DocumentSinkPlugin) -> None:
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def get(self, name: str) -> DocumentSinkPlugin | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[DocumentSinkPlugin]:
        return list(self._plugins.values())

    def dispatch_saved(
        self,
        user_id: str,
        application_id: str,
        application_data: dict[str, Any],
        version_data: dict[str, Any],
        files: dict[str, bytes] | None = None,
    ) -> list[SinkResult]:
        results: list[SinkResult] = []
        for plugin in self._plugins.values():
            if not plugin.is_enabled():
                results.append(SinkResult(plugin_name=plugin.name, status="SKIPPED", details={"reason": "disabled"}))
                continue
            try:
                res = plugin.on_application_saved(
                    user_id=user_id,
                    application_id=application_id,
                    application_data=application_data,
                    version_data=version_data,
                    files=files,
                )
                results.append(res)
            except Exception as exc:
                results.append(
                    SinkResult(
                        plugin_name=plugin.name,
                        status="ERROR",
                        error_message=str(exc),
                    )
                )
        return results

    def dispatch_deleted(
        self,
        user_id: str,
        application_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[SinkResult]:
        results: list[SinkResult] = []
        for plugin in self._plugins.values():
            if not plugin.is_enabled():
                continue
            try:
                res = plugin.on_application_deleted(
                    user_id=user_id,
                    application_id=application_id,
                    metadata=metadata,
                )
                results.append(res)
            except Exception as exc:
                results.append(
                    SinkResult(
                        plugin_name=plugin.name,
                        status="ERROR",
                        error_message=str(exc),
                    )
                )
        return results


# Global default registry instance
registry = PluginRegistry()
