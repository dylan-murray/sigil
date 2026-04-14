"""Adversarial architecture simulation system.

This module analyzes the codebase for potential security weaknesses by modeling
how an adversary would exploit architectural decisions. It runs as a parallel
analysis during the discovery phase and generates Findings that feed into the
existing validation pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sigil.core.security import is_sensitive_file
from sigil.pipeline.models import Finding, Severity


@dataclass(frozen=True)
class WeaknessHeatmap:
    """Heatmap showing architectural components most susceptible to compromise."""
    
    file_scores: dict[str, float] = field(default_factory=dict)
    component_scores: dict[str, float] = field(default_factory=dict)
    overall_vulnerability_score: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file_scores": self.file_scores,
            "component_scores": self.component_scores,
            "overall_vulnerability_score": self.overall_vulnerability_score,
        }


class AdversarialAnalyzer:
    """Analyzes codebase for architectural weaknesses from an adversarial perspective."""
    
    def __init__(self) -> None:
        # Patterns that indicate potential security weaknesses
        self.hardcoded_secret_patterns = [
            r'(?i)(password|passwd|pwd)\s*[=:]\s*["'][^"']{4,}["']',
            r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["'][^"']{10,}["']',
            r'(?i)(secret|private[_-]?key)\s*[=:]\s*["'][^"']{10,}["']',
            r'(?i)(token|auth[_-]?token)\s*[=:]\s*["'][^"']{10,}["']',
            r'(?i)(aws[_-]?access[_-]?key[_-]?id|access[_-]?key)\s*[=:]\s*["'][^"']{10,}["']',
            r'(?i)(aws[_-]?secret[_-]?access[_-]?key|secret[_-]?key)\s*[=:]\s*["'][^"']{10,}["']',
        ]
        
        self.insecure_config_patterns = [
            r'(?i)debug\s*[=:]\s*true',
            r'(?i)ssl[_-]?verify\s*[=:]\s*false',
            r'(?i)verify\s*[=:]\s*false',
            r'(?i)allow[_-]?unsafe\s*[=:]\s*true',
        ]
        
        self.excessive_privilege_patterns = [
            r'(?i)sudo\s+',
            r'(?i)chmod\s+777',
            r'(?i)root\s*:',
            r'(?i)privileged\s*[=:]\s*true',
        ]
        
        self.dependency_risk_patterns = [
            r'(?i)eval\s*\(',
            r'(?i)exec\s*\(',
            r'(?i)pickle\.load',
            r'(?i)yaml\.load(?!\s*Loader)',
        ]
        
        # Compile patterns for efficiency
        self.compiled_hardcoded = [re.compile(p) for p in self.hardcoded_secret_patterns]
        self.compiled_insecure_config = [re.compile(p) for p in self.insecure_config_patterns]
        self.compiled_excessive_privilege = [re.compile(p) for p in self.excessive_privilege_patterns]
        self.compiled_dependency_risk = [re.compile(p) for p in self.dependency_risk_patterns]
    
    async def analyze(self, discovery_data: Any) -> tuple[list[Finding], WeaknessHeatmap]:
        """Analyze discovery data for architectural weaknesses.
        
        Args:
            discovery_data: DiscoveryData object containing repository information
            
        Returns:
            Tuple of (findings, heatmap) where findings are security findings
            and heatmap shows vulnerability distribution
        """
        findings = []
        file_scores: dict[str, float] = {}
        
        # Analyze source files for weaknesses
        source_files = discovery_data.source_text
        if source_files:
            file_findings, file_scores = await self._analyze_source_content(
                source_files, discovery_data.files
            )
            findings.extend(file_findings)
        
        # Analyze manifest files for dependency risks
        manifest_findings, manifest_scores = await self._analyze_manifest(
            discovery_data.manifest, discovery_data.language
        )
        findings.extend(manifest_findings)
        
        # Merge manifest scores into file scores
        for file_path, score in manifest_scores.items():
            file_scores[file_path] = file_scores.get(file_path, 0.0) + score
        
        # Generate heatmap
        heatmap = self._generate_heatmap(file_scores)
        
        return findings, heatmap
    
    async def _analyze_source_content(
        self, 
        source_text: str, 
        file_list: list[str]
    ) -> tuple[list[Finding], dict[str, float]]:
        """Analyze source code content for weaknesses.
        
        Returns:
            Tuple of (findings, file_scores)
        """
        findings = []
        file_scores: dict[str, float] = {}
        
        # Split source text by file markers
        file_sections = self._split_source_by_file(source_text, file_list)
        
        for file_path, content in file_sections.items():
            score = 0.0
            
            # Check for hardcoded secrets
            secret_matches = self._count_pattern_matches(
                content, self.compiled_hardcoded
            )
            if secret_matches > 0:
                severity = Severity.HIGH if secret_matches > 2 else Severity.MEDIUM
                findings.append(Finding(
                    id=f"adversarial-secret-{hash(file_path)}",
                    title=f"Potential hardcoded secrets in {file_path}",
                    description=f"Found {secret_matches} potential hardcoded secret patterns "
                              f"that could be exploited by an adversary",
                    severity=severity,
                    file_path=file_path,
                    confidence=0.7,
                ))
                score += secret_matches * 2.0
            
            # Check for insecure configurations
            config_matches = self._count_pattern_matches(
                content, self.compiled_insecure_config
            )
            if config_matches > 0:
                findings.append(Finding(
                    id=f"adversarial-config-{hash(file_path)}",
                    title=f"Insecure configuration in {file_path}",
                    description=f"Found {config_matches} insecure configuration patterns "
                              f"that could be exploited",
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    confidence=0.8,
                ))
                score += config_matches * 1.5
            
            # Check for excessive privileges
            privilege_matches = self._count_pattern_matches(
                content, self.compiled_excessive_privilege
            )
            if privilege_matches > 0:
                findings.append(Finding(
                    id=f"adversarial-privilege-{hash(file_path)}",
                    title=f"Excessive privilege patterns in {file_path}",
                    description=f"Found {privilege_matches} patterns suggesting excessive privileges",
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    confidence=0.75,
                ))
                score += privilege_matches * 1.5
            
            # Check for dependency risks
            dependency_matches = self._count_pattern_matches(
                content, self.compiled_dependency_risk
            )
            if dependency_matches > 0:
                findings.append(Finding(
                    id=f"adversarial-dependency-{hash(file_path)}",
                    title=f"Risky dependency usage in {file_path}",
                    description=f"Found {dependency_matches} patterns that could lead to "
                              f"dependency-based attacks",
                    severity=Severity.LOW,
                    file_path=file_path,
                    confidence=0.6,
                ))
                score += dependency_matches * 1.0
            
            if score > 0:
                file_scores[file_path] = score
        
        return findings, file_scores
    
    async def _analyze_manifest(
        self, 
        manifest_text: str, 
        language: str
    ) -> tuple[list[Finding], dict[str, float]]:
        """Analyze manifest file for dependency risks.
        
        Returns:
            Tuple of (findings, file_scores)
        """
        findings = []
        file_scores: dict[str, float] = {}
        
        if not manifest_text:
            return findings, file_scores
        
        # Determine manifest file name based on language
        manifest_files = {
            "python": "pyproject.toml",
            "javascript": "package.json", 
            "typescript": "package.json",
            "rust": "Cargo.toml",
            "go": "go.mod",
        }
        
        manifest_file = manifest_files.get(language, "manifest")
        
        # Check for unpinned dependencies (simplified check)
        lines = manifest_text.split('\n')
        unpinned_count = 0
        
        for line in lines:
            line = line.strip()
            if language == "python" and ('>=' in line or '==' not in line and not line.startswith('#')):
                if any(dep in line for dep in ['requests', 'django', 'flask', 'numpy', 'pandas']):
                    unpinned_count += 1
            elif language in ["javascript", "typescript"] and ':' in line and not line.startswith('"'):
                # Simplified JS/TS check
                if not ('"' in line or "'" in line) and not line.startswith('/'):
                    unpinned_count += 1
        
        if unpinned_count > 0:
            findings.append(Finding(
                id=f"adversarial-unpinned-deps-{hash(manifest_text)}",
                title=f"Unpinned dependencies in {manifest_file}",
                description=f"Found {unpinned_count} potentially unpinned dependencies "
                          f"that could lead to supply chain attacks",
                severity=Severity.MEDIUM,
                file_path=manifest_file,
                confidence=0.7,
            ))
            file_scores[manifest_file] = unpinned_count * 1.5
        
        return findings, file_scores
    
    def _split_source_by_file(
        self, 
        source_text: str, 
        file_list: list[str]
    ) -> dict[str, str]:
        """Split source text into sections by file.
        
        Returns:
            Dictionary mapping file paths to their content sections
        """
        file_sections: dict[str, str] = {}
        
        # Simple approach: split by file markers
        sections = source_text.split('\n--- ')
        
        for section in sections:
            if not section.strip():
                continue
                
            # Extract file path from section header
            lines = section.split('\n')
            if lines:
                first_line = lines[0].strip()
                if first_line.endswith(' ---'):
                    file_path = first_line[:-4]  # Remove ' ---'
                    if file_path in file_list:
                        # Content is everything after the first line
                        content = '\n'.join(lines[1:]) if len(lines) > 1 else ""
                        file_sections[file_path] = content
        
        return file_sections
    
    def _count_pattern_matches(self, text: str, patterns: list[re.Pattern]) -> int:
        """Count total matches across all patterns."""
        total = 0
        for pattern in patterns:
            matches = pattern.findall(text)
            total += len(matches)
        return total
    
    def _generate_heatmap(self, file_scores: dict[str, float]) -> WeaknessHeatmap:
        """Generate weakness heatmap from file scores.
        
        Args:
            file_scores: Dictionary mapping file paths to vulnerability scores
            
        Returns:
            WeaknessHeatmap object
        """
        if not file_scores:
            return WeaknessHeatmap()
        
        # Normalize scores to 0-1 range
        max_score = max(file_scores.values()) if file_scores else 1.0
        if max_score == 0:
            max_score = 1.0
            
        normalized_scores = {
            file_path: score / max_score 
            for file_path, score in file_scores.items()
        }
        
        # Group by component (directory)
        component_scores: dict[str, float] = {}
        for file_path, score in normalized_scores.items():
            # Get directory component
            path_obj = Path(file_path)
            component = str(path_obj.parent) if path_obj.parent != Path('.') else 'root'
            component_scores[component] = component_scores.get(component, 0.0) + score
        
        # Normalize component scores
        max_component_score = max(component_scores.values()) if component_scores else 1.0
        if max_component_score == 0:
            max_component_score = 1.0
            
        normalized_component_scores = {
            component: score / max_component_score
            for component, score in component_scores.items()
        }
        
        # Overall vulnerability score is average of top scores
        top_file_scores = sorted(normalized_scores.values(), reverse=True)[:5]
        overall_score = sum(top_file_scores) / len(top_file_scores) if top_file_scores else 0.0
        
        return WeaknessHeatmap(
            file_scores=normalized_scores,
            component_scores=normalized_component_scores,
            overall_vulnerability_score=overall_score,
        )


def create_adversarial_analyzer() -> AdversarialAnalyzer:
    """Factory function to create an AdversarialAnalyzer instance."""
    return AdversarialAnalyzer()