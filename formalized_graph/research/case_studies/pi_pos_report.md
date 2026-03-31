# Case Study: Real.pi_pos

**Theorem Statement:**
```lean
theorem pi_pos : 0 < π :=
  lt_of_lt_of_le (by simp) two_le_pi
```

## 1. LLM Judgment (Human Intuition)
Just by reading the source code, a mathematician would expect these dependencies:
1. `lt_of_lt_of_le` (Explicit call)
2. `Real.pi` (The symbol π)
3. `Real.two_le_pi` (Explicit call)
4. `0 < 2` (The goal of the `by simp` tactic)

## 2. Our Current Parser (Heuristic)
**Found:**
* `Real.two_le_pi`

**Missed:**
* `lt_of_lt_of_le`: Missed because it's a common core lemma often in the `BLACKLIST`.
* `Real.pi`: Missed because it's a symbol (`π`) and our regex-based dependency extractor currently prioritizes alphanumeric identifiers.
* `simp` contents: Completely invisible to static text parsing.

## 3. The "Iceberg" (Ground Truth / LeanDojo)
If we were to run this through the Lean compiler, we would find that `by simp` actually calls:
* `zero_lt_two`
* `Nat.zero_le`
* `Nat.succ_pos`
... and potentially dozens of other foundational field axioms.

## 4. Final Verification (High-Precision Database)
After refining our Lean extraction probe to distinguish between explicit syntactic syntax (`isDirect = 0`) and implicit compilation traces (`is_implicit = 1`), and after implementing geometric range containment to map dependencies strictly to their parent proofs, we ran a definitive verification query on the rebuilt corpus:

```sql
SELECT n_target.full_name, e.is_implicit
FROM nodes n_source
JOIN edges e ON n_source.id = e.source_id
JOIN nodes n_target ON e.target_id = n_target.id
WHERE n_source.full_name = 'Real.pi_pos'
ORDER BY e.is_implicit ASC, n_target.full_name ASC;
```

**Database Output:**
* `Real.pi` (0)
* `Real.two_le_pi` (0)
* `lt_of_lt_of_le` (0)

This matches **100%** of the explicit `LLM Judgment (Human Intuition)` dependencies. It perfectly bypassed the heuristic weaknesses (failing on symbols like `π` or common lemmas like `lt_of_lt_of_le`) while simultaneously filtering out the massive "Iceberg" of hidden tactic resolutions. 

## Conclusion
This case study perfectly illustrates why **Text-Based Parsing** is "Shit" for high-fidelity dependency graphs. It only sees the **explicit tip** of the iceberg. Meanwhile, the raw compiler **InfoTree** captures too much noise. The **Refined Ground Truth** approach (combining compiler ASTs with geometric bounds and syntactic flags) is required to map the actual human-authored logical structure supporting the theorem.
