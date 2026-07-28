"""Category 3: Testing & Stability (25% weight).

Blog principle: 'Measure stability alongside throughput' + 'tests define what correct means.'
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .base import BaseCheck

if TYPE_CHECKING:
    from ..models import CheckResult
    from ..repo_context import RepoContext


@dataclass(frozen=True)
class _SourceLine:
    path: str
    line_number: int
    normalized: str


@dataclass(frozen=True)
class _DuplicationAnalysis:
    total_lines: int
    duplicated_lines: int
    largest_blocks: tuple[str, ...]

    @property
    def percentage(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return self.duplicated_lines / self.total_lines * 100


class TestSuiteExistsCheck(BaseCheck):
    check_id = "test_suite_exists"
    name = "Test Suite"
    description = "Tests present and executed in CI"
    max_points = 3.0
    source = "Kent Beck - tests define what correct means"

    def run(self, context: RepoContext) -> CheckResult:
        has_test_dir = context.has_dir(
            "tests",
            "test",
            "spec",
            "src/test",
            "__tests__",
        )
        has_test_files = context.has_file(
            "tests/*.rs",
            "tests/*.py",
            "tests/*.ts",
            "tests/*.js",
            "test_*.py",
            "*_test.go",
            "*_test.rs",
            "*.test.ts",
            "*.test.js",
            "*.spec.ts",
            "*.spec.js",
        )

        has_tests = has_test_dir or has_test_files

        test_in_ci = context.ci_has_command(
            r"cargo\s+(test|nextest)|pytest|jest|mocha|vitest|go\s+test|rspec|"
            r"gradlew?\s+test|\.\/gradlew\s+test|mvn\s+test|dotnet\s+test"
        )

        if has_tests and test_in_ci:
            return self.pass_result("Tests present and executed in CI")
        if has_tests:
            return self.partial_result(
                1.5,
                "Tests found but not confirmed in CI",
                "Add test execution to your CI pipeline.",
            )
        return self.fail_result(
            "No test suite found",
            "Add tests and run them in CI. As Kent Beck says: "
            "'the test defines what correct means.'",
        )


class FeatureMatrixTestingCheck(BaseCheck):
    check_id = "feature_matrix_testing"
    name = "Feature Matrix Testing"
    description = "Multiple feature/configuration combinations tested in CI"
    max_points = 3.0
    source = "DORA 2025 - stability through comprehensive testing"

    def run(self, context: RepoContext) -> CheckResult:
        test_jobs = [
            job
            for ci in context.ci_configs
            for job in ci.jobs
            if any(
                kw in " ".join(job.commands).lower()
                for kw in ("test", "pytest", "jest", "rspec", "nextest")
            )
        ]

        if len(test_jobs) >= 3:
            names = ", ".join(j.name for j in test_jobs[:5])
            return self.pass_result(f"Multiple test jobs in CI: {names}")

        ci_raw = context.ci_raw_content()
        if "matrix" in ci_raw.lower() or "parallel" in ci_raw.lower():
            return self.pass_result("Matrix/parallel testing strategy found in CI")

        feature_patterns = [
            r"--all-features",
            r"--no-default-features",
            r"--features\s",
            r"NODE_ENV=",
        ]
        found_combos = sum(1 for pattern in feature_patterns if context.ci_has_command(pattern))
        if found_combos >= 2:
            return self.pass_result(f"Feature combination testing found ({found_combos} variants)")

        if len(test_jobs) == 2:
            return self.partial_result(
                1.5,
                "Two test jobs found, consider adding more configurations",
                "Test with different feature flags, environments, or dependency versions.",
            )

        return self.fail_result(
            "Only one test configuration found",
            "Add CI jobs for different feature flags, environments, or dependency versions "
            "(e.g. --all-features, --no-default-features, MSRV check).",
        )


class CoverageMeasurementCheck(BaseCheck):
    check_id = "coverage_measurement"
    name = "Code Coverage"
    description = "Code coverage measured in CI"
    max_points = 4.0
    source = "DORA 2025 - stability feedback loops"

    COVERAGE_PATTERNS = [
        r"llvm-cov|tarpaulin|cargo-llvm-cov",
        r"coverage\.py|pytest-cov|--cov",
        r"istanbul|nyc|c8\s",
        r"jacoco|cobertura",
        r"simplecov",
        r"go\s+tool\s+cover|gocover",
        r"codecov|coveralls",
    ]

    def run(self, context: RepoContext) -> CheckResult:
        for pattern in self.COVERAGE_PATTERNS:
            if context.ci_has_command(pattern):
                return self.pass_result(f"Coverage measurement in CI: {pattern}")

        coverage_config = context.has_file(
            ".codecov.yml",
            "codecov.yml",
            ".coveragerc",
            "coverage.config.js",
            "jest.config.*",
        )
        if coverage_config:
            return self.partial_result(
                2.0,
                f"Coverage config found ({coverage_config}) but not confirmed in CI",
                "Add coverage reporting to your CI pipeline.",
            )

        return self.fail_result(
            "No code coverage measurement found",
            "Add cargo llvm-cov, pytest-cov, istanbul/c8, or equivalent to CI. "
            "Even informational coverage provides a feedback loop.",
        )


class MutationTestingCheck(BaseCheck):
    check_id = "mutation_testing"
    name = "Mutation Testing"
    description = "Mutation testing configured or running"
    max_points = 4.0
    source = "SlopCodeBench - code that 'appears correct but is unreliable'"

    def run(self, context: RepoContext) -> CheckResult:
        if context.ci_has_command(r"cargo[\s-]mutants|stryker|mutmut|pitest|mull"):
            return self.pass_result("Mutation testing found in CI")

        mutation_config = context.has_file(
            "stryker.conf.js",
            "stryker.conf.json",
            ".stryker-tmp",
            "mutmut_config.py",
            ".mutmut",
        )
        if mutation_config:
            return self.partial_result(
                2.0,
                f"Mutation testing config found ({mutation_config})",
                "Add mutation testing to CI, even on a scheduled basis.",
            )

        return self.fail_result(
            "No mutation testing found",
            "Add cargo-mutants (Rust), Stryker (JS/TS), mutmut (Python), or PIT (Java). "
            "Mutation testing catches tests that pass without verifying behavior.",
        )


class CodeDuplicationCheck(BaseCheck):
    check_id = "testing.code_duplication"
    name = "Code Duplication"
    description = "Code duplication measured and controlled in CI"
    max_points = 3.0
    source = "jscpd - copy/paste detection and CI thresholds"

    _MINIMUM_BLOCK_LINES = 5
    _SOURCE_SUFFIXES = frozenset(
        {
            ".cs",
            ".go",
            ".java",
            ".js",
            ".jsx",
            ".kt",
            ".kts",
            ".mjs",
            ".py",
            ".rb",
            ".rs",
            ".swift",
            ".ts",
            ".tsx",
        }
    )
    _EXCLUDED_PARTS = frozenset(
        {
            ".agents",
            ".claude",
            ".codex",
            "__tests__",
            "coverage",
            "example",
            "examples",
            "fixture",
            "fixtures",
            "generated",
            "spec",
            "specs",
            "test",
            "tests",
        }
    )
    _GENERATED_MARKERS = (
        "@generated",
        "automatically generated",
        "code generated",
        "do not edit",
        "<auto-generated",
    )
    _COMMENT_PREFIXES = ("#", "//", "/*", "*/", "*")
    _CI_TOOL_PATTERN = (
        r"\bjscpd\b|kucherenko/jscpd|"
        r"pylint[^\n]*(?:r0801|duplicate-code)|"
        r"sonar(?:-scanner|cloud|qube)|"
        r"(?:pmd|cpd)[^\n]*(?:\bcpd\b|copy.?paste)"
    )
    _BLOCKING_LIMIT_PATTERN = (
        r"(?s)(?=.*\bjscpd\b)(?=.*--threshold(?:=|\s+)\d+)|"
        r"pylint[^\n]*(?:r0801|duplicate-code)|"
        r"sonar[^\n]*qualitygate\.wait\s*=\s*true"
    )
    _CONFIG_FILES = (
        ".jscpd.json",
        ".jscpd.yml",
        ".jscpd.yaml",
        ".pylintrc",
        "pylintrc",
        "sonar-project.properties",
    )

    def run(self, context: RepoContext) -> CheckResult:
        analysis = self._analyze(context)
        if analysis.total_lines < self._MINIMUM_BLOCK_LINES * 2:
            return self.pass_result(
                "Code duplication check does not apply: "
                f"{analysis.total_lines} eligible source lines"
            )

        duplication_score = self._duplication_score(analysis.percentage)
        ci_score, ci_evidence = self._ci_score(context)
        score = duplication_score + ci_score
        evidence = (
            f"Code duplication: {analysis.percentage:.2f}% "
            f"({analysis.duplicated_lines}/{analysis.total_lines} lines); "
            f"CI control: {ci_evidence}"
        )
        remediation = self._remediation(analysis, ci_score)

        if score == self.max_points:
            return self.pass_result(evidence)
        if score > 0:
            return self.partial_result(score, evidence, remediation)
        return self.fail_result(evidence, remediation)

    def _analyze(self, context: RepoContext) -> _DuplicationAnalysis:
        files = [
            path
            for path in context.file_tree
            if self._is_production_source(path) and not self._is_generated(context, path)
        ]
        lines_by_file = {path: self._normalized_lines(context, path) for path in files}
        windows: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)

        for path, lines in lines_by_file.items():
            for start in range(len(lines) - self._MINIMUM_BLOCK_LINES + 1):
                block = tuple(
                    line.normalized for line in lines[start : start + self._MINIMUM_BLOCK_LINES]
                )
                windows[block].append((path, start))

        duplicated_indexes: dict[str, set[int]] = defaultdict(set)
        for occurrences in windows.values():
            self._mark_duplicate_occurrences(occurrences, duplicated_indexes)

        largest_blocks = self._largest_blocks(lines_by_file, duplicated_indexes)
        return _DuplicationAnalysis(
            total_lines=sum(len(lines) for lines in lines_by_file.values()),
            duplicated_lines=sum(len(indexes) for indexes in duplicated_indexes.values()),
            largest_blocks=largest_blocks,
        )

    def _is_production_source(self, path: str) -> bool:
        pure_path = PurePosixPath(path)
        parts = tuple(part.lower() for part in pure_path.parts)
        stem = pure_path.stem.lower()
        if pure_path.suffix.lower() not in self._SOURCE_SUFFIXES:
            return False
        if any(part in self._EXCLUDED_PARTS for part in parts[:-1]):
            return False
        return not (
            stem.startswith("test_")
            or stem.endswith("_test")
            or stem.endswith(".test")
            or stem.endswith(".spec")
        )

    def _is_generated(self, context: RepoContext, path: str) -> bool:
        content = context.read_file(path)
        if content is None:
            return True
        header = "\n".join(content.splitlines()[:5]).lower()
        return any(marker in header for marker in self._GENERATED_MARKERS)

    def _normalized_lines(self, context: RepoContext, path: str) -> list[_SourceLine]:
        content = context.read_file(path)
        if content is None:
            return []

        normalized_lines = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(self._COMMENT_PREFIXES):
                continue
            normalized_lines.append(
                _SourceLine(
                    path=path,
                    line_number=line_number,
                    normalized=re.sub(r"\s+", " ", stripped),
                )
            )
        return normalized_lines

    def _mark_duplicate_occurrences(
        self,
        occurrences: list[tuple[str, int]],
        duplicated_indexes: dict[str, set[int]],
    ) -> None:
        paths = {path for path, _ in occurrences}
        for path, start in occurrences:
            has_match = len(paths) > 1 or any(
                other_path == path and abs(other_start - start) >= self._MINIMUM_BLOCK_LINES
                for other_path, other_start in occurrences
            )
            if has_match:
                duplicated_indexes[path].update(range(start, start + self._MINIMUM_BLOCK_LINES))

    def _largest_blocks(
        self,
        lines_by_file: dict[str, list[_SourceLine]],
        duplicated_indexes: dict[str, set[int]],
    ) -> tuple[str, ...]:
        blocks: list[tuple[int, str]] = []
        for path, indexes in duplicated_indexes.items():
            if not indexes:
                continue
            start = previous = min(indexes)
            for index in sorted(indexes)[1:]:
                if index != previous + 1:
                    blocks.append(self._format_block(lines_by_file[path], start, previous))
                    start = index
                previous = index
            blocks.append(self._format_block(lines_by_file[path], start, previous))

        blocks.sort(key=lambda item: (-item[0], item[1]))
        return tuple(label for _, label in blocks[:3])

    @staticmethod
    def _format_block(lines: list[_SourceLine], start: int, end: int) -> tuple[int, str]:
        count = end - start + 1
        first = lines[start]
        last = lines[end]
        return count, f"{first.path}:{first.line_number}-{last.line_number}"

    @staticmethod
    def _duplication_score(percentage: float) -> float:
        if percentage <= 5:
            return 2.0
        if percentage <= 10:
            return 1.0
        return 0.0

    def _ci_score(self, context: RepoContext) -> tuple[float, str]:
        blocking_tool = context.ci_has_blocking_command(self._CI_TOOL_PATTERN)
        any_tool = context.ci_has_command(self._CI_TOOL_PATTERN)
        has_blocking_limit = context.ci_has_blocking_command(self._BLOCKING_LIMIT_PATTERN)
        raw_ci = context.ci_raw_content()
        has_action_threshold = bool(
            blocking_tool
            and re.search(r"(?im)^\s*threshold\s*:\s*\d+", raw_ci)
            and re.search(r"kucherenko/jscpd", raw_ci, re.IGNORECASE)
        )

        if has_blocking_limit or has_action_threshold:
            return 1.0, "blocking duplication limit found"
        if any_tool:
            return 0.5, "duplication tool runs without a blocking limit"

        config = context.has_file(*self._CONFIG_FILES)
        if config:
            return 0.0, f"configuration found in {config}, but no CI control found"
        return 0.0, "no duplication control found"

    @staticmethod
    def _remediation(analysis: _DuplicationAnalysis, ci_score: float) -> str:
        actions = []
        if analysis.percentage > 5:
            locations = ", ".join(analysis.largest_blocks)
            actions.append(f"Refactor the largest duplicate blocks: {locations}.")
        if ci_score < 1:
            actions.append("Add a blocking CI duplication limit of 5%.")
        return " ".join(actions)


class PropertyBasedTestingCheck(BaseCheck):
    check_id = "property_based_testing"
    name = "Property-Based Testing"
    description = "Property-based or generative testing libraries used"
    max_points = 3.0
    source = "Blog: catching edge cases in AI-generated code"

    def run(self, context: RepoContext) -> CheckResult:
        dep_files = [
            "cargo.toml",
            "pyproject.toml",
            "package.json",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        ]
        patterns = [
            r"proptest|quickcheck|arbtest",
            r"hypothesis",
            r"fast-check|jsverify",
            r"rapid",
            r"jqwik",
        ]
        for dep_file in dep_files:
            for pattern in patterns:
                if context.search_any_file([dep_file, f"*/{dep_file}"], pattern):
                    return self.pass_result(f"Property-based testing library found in {dep_file}")

        test_files = context.find_files(
            "tests/*.rs",
            "tests/*.py",
            "test_*.py",
            "*.test.ts",
            "*PropertyTest.java",
            "*PropertyTest.kt",
        )
        prop_test_patterns = [
            r"proptest!",
            r"@given",
            r"fc\.(assert|property)",
            r"rapid\.Check",
            r"@Property",
        ]
        for tf in test_files:
            for pattern in prop_test_patterns:
                if context.search_file(tf, pattern):
                    return self.pass_result(f"Property-based tests found in {tf}")

        return self.fail_result(
            "No property-based testing found",
            "Add proptest (Rust), hypothesis (Python), fast-check (JS/TS), or jqwik (Java) "
            "for testing invariants with random structured inputs.",
        )


class FuzzTestingCheck(BaseCheck):
    check_id = "fuzz_testing"
    name = "Fuzz Testing"
    description = "Fuzz testing targets present"
    max_points = 3.0
    source = "Blog: 80% problem - catching what AI misses"

    def run(self, context: RepoContext) -> CheckResult:
        dep_files = [
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        ]
        for dep_file in dep_files:
            if context.search_any_file([dep_file, f"*/{dep_file}"], "jazzer-junit"):
                return self.pass_result(f"Jazzer fuzz testing library found in {dep_file}")

        fuzz_dir = context.has_dir("fuzz", "fuzz_targets", "fuzzing")
        if fuzz_dir:
            return self.pass_result(f"Fuzz testing directory found: {fuzz_dir}")

        fuzz_file = context.has_file(
            "fuzz/fuzz_targets/*.rs",
            "fuzz/*.py",
            "fuzz_test.go",
            "*_fuzz_test.go",
            "*FuzzTest.java",
            "*FuzzTest.kt",
        )
        if fuzz_file:
            return self.pass_result(f"Fuzz target found: {fuzz_file}")

        if context.ci_has_command(r"cargo\s+fuzz|go\s+test.*-fuzz|afl-fuzz|honggfuzz"):
            return self.pass_result("Fuzz testing found in CI")

        return self.fail_result(
            "No fuzz testing found",
            "Add fuzz targets for parsing-heavy and input-handling code paths.",
        )


class ContractTestsCheck(BaseCheck):
    check_id = "contract_tests"
    name = "Contract / Compatibility Tests"
    description = "Tests that verify external interface contracts or compatibility"
    max_points = 3.0
    source = "OpenAI Harness Engineering - mechanical constraints"

    def run(self, context: RepoContext) -> CheckResult:
        contract_files = context.find_files(
            "*contract*",
            "*golden*",
            "*compat*",
            "*snapshot*",
            "*fixture*",
        )
        test_contract_files = [
            f
            for f in contract_files
            if any(ext in f for ext in (".rs", ".py", ".ts", ".js", ".go", ".json"))
        ]
        if test_contract_files:
            names = ", ".join(test_contract_files[:3])
            return self.pass_result(f"Contract/compatibility tests found: {names}")

        if context.ci_has_command(r"golden|snapshot|contract"):
            return self.pass_result("Contract/snapshot testing found in CI")

        return self.fail_result(
            "No contract or compatibility tests found",
            "Add contract tests that verify external interface stability "
            "(golden fixtures, snapshot tests, wire-format checks).",
        )


class TestsBlockingInCICheck(BaseCheck):
    check_id = "tests_blocking_ci"
    name = "Tests Block Merge"
    description = "Test jobs are blocking (not allow_failure)"
    max_points = 2.0
    source = "DORA 2025 - stability metrics"

    def run(self, context: RepoContext) -> CheckResult:
        test_keywords = ("test", "pytest", "jest", "rspec", "nextest", "spec")

        blocking_test_jobs = []
        non_blocking_test_jobs = []

        for ci in context.ci_configs:
            for job in ci.jobs:
                is_test_job = any(
                    kw in job.name.lower() or any(kw in cmd.lower() for cmd in job.commands)
                    for kw in test_keywords
                )
                if not is_test_job:
                    continue
                if job.allow_failure:
                    non_blocking_test_jobs.append(job.name)
                else:
                    blocking_test_jobs.append(job.name)

        if blocking_test_jobs and not non_blocking_test_jobs:
            return self.pass_result(
                f"All test jobs are blocking: {', '.join(blocking_test_jobs[:3])}"
            )

        if blocking_test_jobs:
            return self.partial_result(
                1.0,
                f"Some test jobs are allow_failure: {', '.join(non_blocking_test_jobs[:3])}",
                "Make all test jobs blocking to prevent merging broken code.",
            )

        if non_blocking_test_jobs:
            return self.fail_result(
                f"Test jobs found but all are allow_failure: "
                f"{', '.join(non_blocking_test_jobs[:3])}",
                "Remove allow_failure from test jobs.",
            )

        return self.fail_result(
            "No test jobs found in CI",
            "Add test execution to CI as a blocking job.",
        )


TESTING_CHECKS: list[BaseCheck] = [
    TestSuiteExistsCheck(),
    FeatureMatrixTestingCheck(),
    CoverageMeasurementCheck(),
    MutationTestingCheck(),
    CodeDuplicationCheck(),
    PropertyBasedTestingCheck(),
    FuzzTestingCheck(),
    ContractTestsCheck(),
    TestsBlockingInCICheck(),
]
