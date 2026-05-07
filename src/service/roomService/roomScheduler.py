"""房间调度状态机，管理发言位、轮次、跳过窗口和状态转换。"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from constants import RoomState, RoomType, SpecialAgent
from dal.db import gtAgentManager, gtRoomManager
from model.dbModel.gtRoom import GtRoom
from service import messageBus
from constants import MessageBusTopic

logger = logging.getLogger("service.roomService")


class RoomScheduler:
    """房间调度状态机。

    ChatRoom 持有 RoomScheduler 实例，将调度逻辑委托给它。
    通过构造函数注入 gt_room（用于发布事件）和 get_read_index（用于持久化）。
    """

    SYSTEM_MEMBER_ID = int(SpecialAgent.SYSTEM.value)
    OPERATOR_MEMBER_ID = int(SpecialAgent.OPERATOR.value)

    def __init__(
        self,
        *,
        room_key: str,
        gt_room: GtRoom,
        get_read_index: Callable[[], Dict[int, int]],
    ):
        self._key: str = room_key
        self._gt_room: GtRoom = gt_room
        self._get_read_index = get_read_index

        self._current_speaker_index: int = 0
        self._round_count: int = 0
        self._current_round_skipped_set: set[int] = set()
        self.current_turn_has_content: bool = False
        self._state: RoomState = RoomState.INIT
        self._last_speaker_id: int | None = None

    # ─── 外部可读属性 ──────────────────────────────────────

    @property
    def state(self) -> RoomState:
        return self._state

    @property
    def current_speaker_index(self) -> int:
        """当前发言人索引（供持久化等外部使用）。"""
        return self._current_speaker_index

    def set_current_speaker_index(self, index: int | None = None) -> None:
        """从持久化数据恢复发言位，重置跳过窗口。"""
        self._round_count = 0
        if index is not None and 0 <= index < len(self._gt_room.agent_ids):
            self._current_speaker_index = index
        else:
            self._current_speaker_index = 0
        self._current_round_skipped_set = set()
        self.current_turn_has_content = False
        self._last_speaker_id = None

    # ─── turn 生命周期 ──────────────────────────────────────

    async def handle_finish_request(self, caller_agent_id: int) -> bool:
        """处理 Agent 的结束发言请求：校验 → 记录跳过 → 推进 → 持久化 + 发布。"""
        if self._state == RoomState.INIT:
            logger.warning("房间 %s 仍处于 INIT，收到结束轮次请求", self._key)

        # IDLE 唤醒：重置轮次状态后直接调度
        if self._state == RoomState.IDLE:
            logger.info("房间 %s 由 agent=%s 从 IDLE 唤醒调度",
                        self._key, gtAgentManager.get_agent_name(caller_agent_id))
            self._last_speaker_id = None
            self._round_count = 0
            self._current_round_skipped_set = set()
            self.current_turn_has_content = False
            self._state = RoomState.SCHEDULING
            # PRIVATE（或 GROUP ≤2）中 OPERATOR 本身处于当前发言位时，先推进一步
            if (self.get_current_turn_agent_id() == self.OPERATOR_MEMBER_ID
                    and not self._should_skip()):
                self._go_next_agent()
            next_id = self._advance_to_first_dispatchable()
            if next_id is not None:
                self.publish_status(next_id, need_scheduling=True)
            else:
                if self._state == RoomState.SCHEDULING:
                    self._state = RoomState.IDLE
                self.publish_status()
            return True

        current_id = self.get_current_turn_agent_id()
        current_name = gtAgentManager.get_agent_name(current_id)
        if caller_agent_id != current_id:
            logger.warning("房间 %s 拒绝结束轮次申请：agent=%s 并非当前发言人 agent=%s",
                           self._key, gtAgentManager.get_agent_name(caller_agent_id), current_name)
            return False

        logger.info(
            "房间 %s 由 agent=%s 结束本轮行动 (has_content=%s, speaker_index=%d/%d, turn_count=%d)",
            self._key, current_name,
            self.current_turn_has_content, self._current_speaker_index, len(self._gt_room.agent_ids), self._round_count,
        )

        if not self.current_turn_has_content:
            self._current_round_skipped_set.add(current_id)

        if self._stop_if_done():
            return True

        self._last_speaker_id = caller_agent_id
        self._go_next_agent()
        await self.persist_state()
        next_id = self._advance_to_first_dispatchable()
        if next_id is not None:
            self.publish_status(next_id, need_scheduling=True)
        else:
            if self._state == RoomState.SCHEDULING:
                self._state = RoomState.IDLE
            self.publish_status()
        return True

    def activate(self) -> None:
        """激活：退出 INIT → 找下一位可调度 Agent → 决定状态 → 发布。"""
        self._state = RoomState.SCHEDULING
        next_id = self._advance_to_first_dispatchable()
        if next_id is not None:
            self.publish_status(current_turn_agent_id=next_id, need_scheduling=True)
        else:
            if self._state == RoomState.SCHEDULING:
                self._state = RoomState.IDLE
            self.publish_status()

    def cancel_current_turn(self) -> None:
        """人工停止 → IDLE。"""
        if self._state != RoomState.SCHEDULING:
            return
        self.current_turn_has_content = False
        self._state = RoomState.IDLE
        logger.info("房间 %s 当前 turn 被人工停止，切回 IDLE 等待新消息唤醒", self._key)
        self.publish_status(current_turn_agent_id=None)

    def on_message(self, sender_id: int) -> None:
        """收到消息时标记当前 turn 是否有内容产出。"""
        if sender_id == self.get_current_turn_agent_id():
            self.current_turn_has_content = True

    def is_idle(self) -> bool:
        return self._state == RoomState.IDLE

    def get_current_turn_agent_id(self) -> int:
        assert self._gt_room.agent_ids, f"房间 {self._key} 没有任何参与者"
        return self._gt_room.agent_ids[self._current_speaker_index]

    def _go_next_agent(self) -> None:
        self._current_speaker_index = (self._current_speaker_index + 1) % len(self._gt_room.agent_ids)
        if self._current_speaker_index == 0:
            self._round_count += 1
        self.current_turn_has_content = False

    def _should_skip(self) -> bool:
        """当前发言人是否应被自动跳过并继续推进（多人群聊中的 Operator）。"""
        return (
            self.get_current_turn_agent_id() == self.OPERATOR_MEMBER_ID
            and self._gt_room.type == RoomType.GROUP
            and len(self._gt_room.agent_ids) > 2
        )

    def _should_stop(self) -> bool:
        """当前是否已达到停止调度的条件。"""
        if self._gt_room.type == RoomType.PRIVATE:
            # 私聊停止条件 1：所有 AI 成员均已跳过发言
            ai_ids = {aid for aid in self._gt_room.agent_ids if aid != self.OPERATOR_MEMBER_ID}
            if ai_ids and ai_ids.issubset(self._current_round_skipped_set):
                return True
            # 私聊停止条件 2：轮到同一个 agent，且上次也是该 agent 发言（Operator 未介入）
            if (self._last_speaker_id is not None
                    and self._last_speaker_id == self.get_current_turn_agent_id()):
                return True
            return False
        if self._gt_room.type == RoomType.GROUP:
            # 群聊停止条件 1：已完成最大轮次（_go_next_agent 末位绕回时 round_count 自增至 max_rounds）
            if self._gt_room.max_rounds > 0 and self._round_count >= self._gt_room.max_rounds:
                return True
            # 群聊停止条件 2：所有 AI 成员均已跳过发言
            ai_ids = {aid for aid in self._gt_room.agent_ids if aid != self.OPERATOR_MEMBER_ID}
            return bool(ai_ids and ai_ids.issubset(self._current_round_skipped_set))
        return False

    def _advance_to_first_dispatchable(self) -> Optional[int]:
        """从当前发言位向前推进，找到下一个可调度的 Agent。"""
        while True:
            if self._stop_if_done():
                return None

            agent_id = self.get_current_turn_agent_id()

            if self._should_skip():
                self._current_round_skipped_set.add(agent_id)
                self._go_next_agent()
                continue

            if agent_id == self.OPERATOR_MEMBER_ID:
                return None  # 等待外部输入

            return agent_id

    def _stop_if_done(self) -> bool:
        """若已到终止条件，切换到 IDLE 并广播，返回 True；否则返回 False。"""
        if not self._should_stop():
            return False
        self._state = RoomState.IDLE
        logger.info("房间 %s 停止调度", self._key)
        self.publish_status(current_turn_agent_id=None)
        return True

    # ─── 外部动作 ───────────────────────────────────────────

    def publish_status(self, current_turn_agent_id: int | None = None, *,
                       need_scheduling: bool = False) -> None:
        """广播房间状态，不推送 INIT 状态。"""
        if self._state == RoomState.INIT:
            return
        messageBus.publish(
            MessageBusTopic.ROOM_STATUS_CHANGED,
            gt_room=self._gt_room,
            state=self._state,
            current_turn_agent_id=current_turn_agent_id,
            need_scheduling=need_scheduling,
        )

    async def persist_state(self) -> None:
        """持久化 speaker_index 与各 Agent 已读进度。"""
        if self._state == RoomState.INIT:
            return
        id_keyed = {str(k): v for k, v in self._get_read_index().items()}
        await gtRoomManager.update_room_state(self._gt_room.id, id_keyed, self._current_speaker_index)
