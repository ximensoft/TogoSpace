from __future__ import annotations

from typing import Any, Mapping

from constants import DriverType
from service.funcToolService.tools import filter_external_allowed_tools
from .base import AgentDriverConfig
from .nativeDriver import NativeAgentDriver
from .claudeSdkDriver import ClaudeSdkAgentDriver
from .tspDriver import TspAgentDriver


def normalize_driver_config(role_template_cfg: Mapping[str, Any] | Any) -> AgentDriverConfig:
    if hasattr(role_template_cfg, "model_dump"):
        role_template_cfg = role_template_cfg.model_dump()

    driver_cfg = role_template_cfg.get("driver")
    driver_type = DriverType.value_of(driver_cfg) or DriverType.NATIVE
    options = {}
    if driver_type == DriverType.CLAUDE_SDK and role_template_cfg.get("allowed_tools") is not None:
        options["allowed_tools"] = filter_external_allowed_tools(role_template_cfg.get("allowed_tools", []))
    return AgentDriverConfig(driver_type=driver_type, options=options)


def build_agent_driver(host, driver_config: AgentDriverConfig):
    driver_type = driver_config.driver_type
    if isinstance(driver_type, str):
        driver_type = DriverType.value_of(driver_type) or DriverType.NATIVE
        driver_config.driver_type = driver_type

    if driver_type == DriverType.NATIVE:
        return NativeAgentDriver(host, driver_config)
    if driver_type == DriverType.CLAUDE_SDK:
        return ClaudeSdkAgentDriver(host, driver_config)
    if driver_type == DriverType.TSP:
        return TspAgentDriver(host, driver_config)
    raise ValueError(f"未知 agent driver 类型: {driver_type}")
