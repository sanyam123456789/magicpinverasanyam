"""In-memory state for the bot. Thread-safe.

Holds every context the judge pushes to POST /v1/context. Contexts are kept in memory
for the whole test (challenge-testing-brief.md §2.1) and wiped on POST /v1/teardown (§11).
"""
import threading
import time
from datetime import datetime, timezone

SCOPES = ("category", "merchant", "customer", "trigger")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._started = time.monotonic()
        self._init_state()

    def _init_state(self) -> None:
        # (scope, context_id) -> {"version": int, "payload": dict}
        self.contexts: dict[tuple[str, str], dict] = {}
        # conversation_id -> {"merchant_id", "customer_id", "trigger_id", "send_as", "turns": [...], "ended": bool, ...}
        self.conversations: dict[str, dict] = {}
        # merchant_id -> {"auto_replies": int, "hostile": int, "suppressed": bool}
        # Kept per merchant (not per conversation): the judge's auto-reply scenario changes conversation_id every turn.
        # `suppressed` is only set for a hostile merchant (api-call-examples.md:529) and only stops proactive /v1/tick sends.
        self.merchant_flags: dict[str, dict] = {}
        self.inbound_seen: dict[str, dict[str, int]] = {}   # merchant_id -> {normalised inbound text: count}
        self.suppressed_customers: set[str] = set()
        # Proactive-send bookkeeping (brief §4.3 suppression_key). Keys are scoped to (merchant, customer, key) because
        # a category-level key such as "research:dentists:2026-W17" is shared by every dentist.
        self.sent_trigger_ids: set[str] = set()
        self.sent_keys: set[tuple] = set()

    def reset(self) -> None:
        with self.lock:
            self._init_state()

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self._started)

    def put_context(self, scope: str, context_id: str, version: int, payload: dict) -> tuple[bool, int]:
        """Store a context. Returns (accepted, current_version).

        A version that is not strictly higher than the stored one is rejected
        (api-call-examples.md Example 1.5: same version -> 409 stale_version).
        A higher version replaces the old one atomically (Example 1.6).
        """
        with self.lock:
            current = self.contexts.get((scope, context_id))
            if current is not None and current["version"] >= version:
                return False, current["version"]
            self.contexts[(scope, context_id)] = {"version": version, "payload": payload}
            return True, version

    def get(self, scope: str, context_id: str) -> dict | None:
        with self.lock:
            entry = self.contexts.get((scope, context_id))
            return entry["payload"] if entry else None

    def conversation(self, conversation_id: str, **defaults) -> dict:
        """Get (or create) the state of a conversation. Caller should hold self.lock while mutating it."""
        with self.lock:
            conv = self.conversations.get(conversation_id)
            if conv is None:
                conv = {"merchant_id": None, "customer_id": None, "trigger_id": None, "send_as": None,
                        "turns": [], "ended": False, "options": [], "booked": None}
                self.conversations[conversation_id] = conv
            for key, value in defaults.items():
                if value is not None and not conv.get(key):
                    conv[key] = value
            return conv

    def flags(self, merchant_id: str) -> dict:
        with self.lock:
            return self.merchant_flags.setdefault(merchant_id, {"auto_replies": 0, "hostile": 0, "suppressed": False})

    def bodies_sent_to(self, merchant_id: str) -> list[str]:
        """Every message we have sent to this merchant (or to its customers), for anti-repetition."""
        with self.lock:
            return [t["body"] for c in self.conversations.values() if c.get("merchant_id") == merchant_id
                    for t in c["turns"] if t["from"] in ("vera", "merchant_on_behalf")]

    def counts(self) -> dict[str, int]:
        with self.lock:
            counts = {scope: 0 for scope in SCOPES}
            for scope, _ in self.contexts:
                counts[scope] += 1
            return counts
