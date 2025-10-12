from dataclasses import dataclass, field
from collections import defaultdict
import string

@dataclass
class EnvSpec:
    name: str
    caption: str
    starred: bool = False
    counter: str | None = None   # theorems adhere to a counter
    within: str | None = None    # parent counter

@dataclass
class TheoremNumberer:
    parents: dict = field(default_factory=dict)                 # child_counter -> parent_counter
    children: defaultdict = field(default_factory=lambda: defaultdict(set))
    counters: defaultdict = field(default_factory=lambda: defaultdict(int))
    envs: dict = field(default_factory=dict)                    # env -> EnvSpec
    swapped: bool = False                                       # amsthm's \swapnumbers (optional)

    # NEW: appendix handling
    in_appendix: bool = False                                   # toggle when you're in appendix
    alpha_roots: set[str] = field(default_factory=lambda: {"section"})  # counters to render A,B,C,...

    # --- definitions ---
    def define_newtheorem(self, starred: bool, env: str, shared: str | None,
                          caption: str, within: str | None):
        if env in self.envs:
            raise ValueError(f"Environment '{env}' already defined")

        if shared and within:
            print("ERR", starred, env, shared, caption, within)
            raise ValueError(f"Use either shared=[{shared}] or within=[{within}], not both.")

        counter = shared if shared else env
        self.envs[env] = EnvSpec(env, caption, starred, counter, within)

        if within:
            self.parents[counter] = within
            self.children[within].add(counter)
            self._ensure_counter(within)

        self._ensure_counter(counter)

    def numberwithin(self, ctr: str, within: str):
        self._ensure_counter(ctr)
        self._ensure_counter(within)
        old = self.parents.get(ctr)
        if old and ctr in self.children[old]:
            self.children[old].remove(ctr)
        self.parents[ctr] = within
        self.children[within].add(ctr)

    # --- document flow ---
    def increment(self, counter: str):
        """Call when a structural parent advances (e.g., \\section)."""
        self._ensure_counter(counter)
        self.counters[counter] += 1
        # reset all descendants (like amsthm)
        for ch in self._descendants(counter):
            self.counters[ch] = 0

    def begin(self, env: str, opt_headnote: str | None = None) -> str:
        """Simulate \\begin{env}… → return amsthm-like heading string."""
        spec = self.envs[env]
        if spec.starred:
            head = spec.caption
            if opt_headnote:
                head += f" ({opt_headnote})"
            return head  # unnumbered

        # step the counter the env uses
        self.counters[spec.counter] += 1
        num = self._formatted_number(spec.counter)
        if self.swapped:
            headcore = f"{num} {spec.caption}"
        else:
            headcore = f"{spec.caption} {num}"
        if opt_headnote:
            headcore += f" ({opt_headnote})"
        return headcore

    # --- helpers ---
    def _ensure_counter(self, c: str):
        _ = self.counters[c]  # touch to initialize

    def _descendants(self, counter: str):
        stack = [counter]
        seen = set()
        out = set()
        while stack:
            c = stack.pop()
            for ch in self.children.get(c, ()):
                if ch not in seen:
                    seen.add(ch)
                    out.add(ch)
                    stack.append(ch)
        return out

    def _formatted_number(self, counter: str) -> str:
        """
        Build chain root -> counter, join values with dots.
        If in appendix mode, render alpha for counters in alpha_roots (e.g., section -> A,B,C,...).
        Descendants remain numeric (A.1, A.2, ...).
        """
        chain = []
        c = counter
        while c:
            chain.append(c)
            c = self.parents.get(c)
        chain.reverse()

        parts: list[str] = []
        for c in chain:
            n = self.counters[c]
            if self.in_appendix and c in self.alpha_roots:
                parts.append(self._to_alpha(n))
            else:
                parts.append(str(n))
        return ".".join(parts) + "."

    @staticmethod
    def _to_alpha(n: int) -> str:
        """
        1 -> 'A', 2 -> 'B', ..., 26 -> 'Z', 27 -> 'AA', etc.
        If n == 0 (before first increment), show 'A' if you prefer, but
        usually counters are incremented before formatting.
        """
        if n <= 0:
            return "A"
        n0 = n
        out = []
        while n0 > 0:
            n0, rem = divmod(n0 - 1, 26)
            out.append(chr(ord('A') + rem))
        return "".join(reversed(out))
