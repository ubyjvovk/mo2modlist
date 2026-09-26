"""Finite Nexus candidate graph backed by vendored resolvelib 1.2.1.

Nexus materializes its own version ranges. We intersect these finite domains;
arbitrary upstream version strings are never treated as SemVer.
"""
from dataclasses import dataclass
from decimal import Decimal

from ._vendor.resolvelib import AbstractProvider, BaseReporter, Resolver, ResolutionImpossible, ResolutionTooDeep
from .acquisition import InputRequired
from .core import PackError, json_digest
from .nexus import candidate_groups


@dataclass(frozen=True)
class Requirement:
    identifier: str
    allowed: frozenset
    reason: tuple


@dataclass(frozen=True)
class Candidate:
    identifier: str
    token: str


class CandidateProvider(AbstractProvider):
    def __init__(self, nexus, supplemental, progress, installed_dlcs):
        self.nexus, self.supplemental, self.progress = nexus, supplemental, progress
        self.records, self.by_identifier, self.dependencies, self.groups = {}, {}, {}, {}
        self.installed_dlcs = installed_dlcs

    def impossible(self, candidate, reason):
        identifier = "unsatisfied:" + candidate.token
        self.by_identifier[identifier] = []
        requirements = [Requirement(identifier, frozenset(), tuple(reason))]
        self.dependencies[candidate] = requirements
        return requirements

    def register(self, source, lineage, position, reason):
        identifier = f"nexus:{source['game']}:lineage:{lineage}"
        candidate = Candidate(identifier, json_digest(source))
        if candidate not in self.records:
            self.records[candidate] = {"source": source, "position": Decimal(position), "reason": reason}
            self.by_identifier.setdefault(identifier, []).append(candidate)
        return candidate

    def pin(self, source, reason):
        metadata = self.nexus.metadata(source)
        version = metadata["version"]
        candidate = self.register(source, str(version["file"]["id"]), version.get("position", "0"), reason)
        self.records[candidate]["metadata"] = metadata
        return Requirement(candidate.identifier, frozenset((candidate.token,)), tuple(reason))

    def identify(self, requirement_or_candidate):
        return requirement_or_candidate.identifier

    def get_preference(self, identifier, resolutions, candidates, information, backtrack_causes):
        return len(list(candidates[identifier])), identifier

    def find_matches(self, identifier, requirements, incompatibilities):
        constraints = list(requirements[identifier])
        excluded = set(incompatibilities[identifier])
        allowed = set.intersection(*(set(r.allowed) for r in constraints))
        result = [c for c in self.by_identifier[identifier] if c.token in allowed and c not in excluded]
        return sorted(result, key=lambda c: (-self.records[c]["position"], c.token))

    def is_satisfied_by(self, requirement, candidate):
        return requirement.identifier == candidate.identifier and candidate.token in requirement.allowed

    def get_dependencies(self, candidate):
        if candidate in self.dependencies:
            return self.dependencies[candidate]
        record = self.records[candidate]
        if "choiceTarget" in record:
            target = record["choiceTarget"]
            result = [Requirement(target.identifier, frozenset((target.token,)), tuple(record["reason"]))]
            self.dependencies[candidate] = result
            return result
        source, reason = record["source"], record["reason"]
        self.progress("Resolving candidate " + " -> ".join(reason))
        metadata = record.get("metadata") or self.nexus.metadata(source)
        record["metadata"] = metadata
        if str(metadata["version"]["file"]["id"]) != candidate.identifier.rsplit(":", 1)[-1]:
            raise PackError("Nexus candidate lineage changed during resolution")
        if self.installed_dlcs is not None:
            for definition in metadata.get("raw", {}).get("dlc_dependency_definitions", []):
                targets = {str(target["dlc_id"]) for target in definition["dlc_targets"]}
                if not targets & self.installed_dlcs:
                    return self.impossible(candidate, reason + ["unavailable DLC " + str(definition["id"])])
        extra = self.supplemental(source, metadata, reason) if self.supplemental else None
        if not metadata["complete"] and extra is None:
            raise InputRequired("dependency-metadata", "Candidate dependency metadata is unknown; provide a recipe", source=source, chain=reason)
        result = [self.pin(required, chain) for required, chain in (extra or [])]
        definitions = {}
        if metadata["complete"]:
            for definition_id, choices in candidate_groups(metadata, allow_empty=True):
                if not choices:
                    return self.impossible(candidate, reason + ["empty Nexus dependency " + definition_id])
                targets = [self.register(selected, lineage, version["position"], reason + ["nexus-definition-" + definition_id])
                           for lineage, version, selected in choices]
                identifiers = {target.identifier for target in targets}
                if len(identifiers) == 1:
                    requirement = Requirement(targets[0].identifier, frozenset(t.token for t in targets), tuple(reason + ["nexus-definition-" + definition_id]))
                else:
                    # An OR between different components is a virtual choice
                    # node whose candidate pins exactly one concrete component.
                    identifier = "alternative:" + candidate.token + ":" + definition_id
                    virtual = []
                    for index, target in enumerate(targets):
                        choice = Candidate(identifier, target.token)
                        self.records[choice] = {"choiceTarget": target, "position": Decimal(-index), "reason": reason + ["nexus-definition-" + definition_id]}
                        virtual.append(choice)
                    self.by_identifier[identifier] = virtual
                    requirement = Requirement(identifier, frozenset(c.token for c in virtual), tuple(reason + ["nexus-definition-" + definition_id]))
                definitions[definition_id] = requirement.identifier
                result.append(requirement)
        self.groups[candidate] = definitions
        self.dependencies[candidate] = result
        return result


class Reporter(BaseReporter):
    def __init__(self, progress):
        self.progress = progress
        self.backtracks = 0

    def starting_round(self, index):
        self.progress(f"Solving dependency candidates: round {index + 1}")

    def rejecting_candidate(self, criterion, candidate):
        self.backtracks += 1


def solve_nexus(roots, nexus, *, supplemental=None, progress=lambda text: None, installed_dlcs=None):
    provider = CandidateProvider(nexus, supplemental, progress, installed_dlcs)
    requirements = [provider.pin(source, reason) for source, reason in roots]
    reporter = Reporter(progress)
    try:
        result = Resolver(provider, reporter).resolve(requirements, max_rounds=10000)
    except ResolutionImpossible as exc:
        chains = sorted({" -> ".join(cause.requirement.reason) for cause in exc.causes})
        raise PackError("No compatible Nexus dependency solution: " + "; versus ".join(chains)) from None
    except ResolutionTooDeep:
        raise PackError("Dependency search exceeded its round limit; no installation plan was finalized") from None
    selections, components = {}, {}
    for candidate in result.mapping.values():
        record = provider.records[candidate]
        if "source" not in record:
            continue
        components[candidate.identifier] = record["source"]
        choices = {}
        for definition, identifier in provider.groups.get(candidate, {}).items():
            selected = result.mapping[identifier]
            selected_record = provider.records[selected]
            if "choiceTarget" in selected_record:
                selected_record = provider.records[selected_record["choiceTarget"]]
            choices[definition] = selected_record["source"]
        selections[json_digest(record["source"])] = choices
    return {"engine": "resolvelib-1.2.1", "components": components, "selections": selections, "backtracks": reporter.backtracks}
