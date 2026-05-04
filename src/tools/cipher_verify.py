from __future__ import annotations

import re

from src.core.state import CipherSpec


def _norm(s: str) -> str:
    return s.strip().upper().replace(" ", "")


def verify_cipher(spec: CipherSpec, expected_solution: str, answer: str) -> bool:
    if spec.type == "caesar":
        return _norm(answer) == _norm(expected_solution)

    if spec.type in {
        "digit_code",
        "logic_puzzle",
        "logic_easy",
        "logic_medium",
        "logic_hard",
        "cascade",
    }:
        only_digits = re.sub(r"\D", "", answer)
        return only_digits == _norm(expected_solution)

    if spec.type in {"sudoku2", "sudoku4", "sudoku6"}:
        size = int(spec.spec.get("size", 4))
        nums = [int(x) for x in re.findall(r"\d", answer)]
        if len(nums) != size * size:
            return False
        cand = "\n".join(
            " ".join(str(n) for n in nums[i : i + size])
            for i in range(0, size * size, size)
        )
        return _norm(cand.replace("\n", "")) == _norm(expected_solution.replace("\n", ""))

    return False
