"""
orchestrator.py
AEGIS — The central workflow pipeline (Step 10 in build order)

Responsibility:
  Coordinates the execution of all agents in the correct order.
  Handles the Verifier <-> Triage retry loop (max 1 retry).
  Runs Dispatch and Hospital Matcher in parallel.
  Aggregates all AgentResults into the final trace.
  Calculates the global requires_human_review flag.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator, Union

from models.input import IncidentInput
from models.output import FinalOutput, FinalDecision, MapData, MapLocation, MapAmbulance, MapHospital
from models.agent_result import AgentResult
from data import mock_store

# Import all agents
from agents import intake
from agents import triage
from agents import verifier
from agents import ambulance_classifier
from agents import dispatch
from agents import hospital_matcher
from agents import admission_formalities

logger = logging.getLogger(__name__)


async def process_incident_stream(incident_input: IncidentInput) -> AsyncGenerator[Union[AgentResult, FinalOutput], None]:
    """
    Generator pipeline entry point.
    Executes the AEGIS workflow and yields AgentResult events as they complete,
    followed by the FinalOutput as the last event.
    """
    logger.info("Orchestrator: Starting streaming pipeline for incident %s", incident_input.incident_id)
    
    trace: list[AgentResult[Any]] = []
    requires_human_review = False
    
    def _update_state(res: AgentResult[Any]):
        trace.append(res)
        nonlocal requires_human_review
        if res.confidence < 0.5:
            requires_human_review = True

    # -----------------------------------------------------------------------
    # 1. Intake Agent
    # -----------------------------------------------------------------------
    intake_res = await intake.run(incident_input)
    _update_state(intake_res)
    yield intake_res
    
    # Extract data for downstream
    consolidated_text = intake_res.result.consolidated_text
    caller_location = intake_res.result.location
    
    # -----------------------------------------------------------------------
    # 2 & 3. Triage <-> Verifier Loop (Max 1 retry)
    # -----------------------------------------------------------------------
    triage_input = triage.TriageInput(
        incident_id=incident_input.incident_id,
        consolidated_text=consolidated_text
    )
    triage_res = await triage.run(triage_input)
    _update_state(triage_res)
    yield triage_res
    
    final_severity = triage_res.result.severity_score
    
    verifier_input = verifier.VerifierInput(
        incident_id=incident_input.incident_id,
        consolidated_text=consolidated_text,
        triage_severity_score=final_severity
    )
    verifier_res = await verifier.run(verifier_input)
    _update_state(verifier_res)
    yield verifier_res
    
    if not verifier_res.result.agrees:
        logger.info("Orchestrator: Verifier disagreed with Triage. Retrying Triage once.")
        # Retry Triage once. We just call it again.
        # In a more complex system, we'd pass the verifier's feedback to the Triage LLM.
        # For Phase 1, we just re-run Triage and see if it changes its mind, or we can just adopt the verifier's score.
        # Wait, the rule says "Verifier↔Triage disagreement loop is capped at exactly 1 retry. If still disagreeing, set requires_human_review: true"
        # Since Triage agent is currently stateless, calling it again with the exact same input will likely yield the same result.
        # To make it meaningful, we adopt the verifier's recommended_score if valid, else we flag for review.
        # Actually, let's strictly re-run Triage. If it still disagrees, we flag.
        retry_triage_res = await triage.run(triage_input)
        _update_state(retry_triage_res)
        yield retry_triage_res
        
        final_severity = retry_triage_res.result.severity_score
        
        retry_verifier_input = verifier.VerifierInput(
            incident_id=incident_input.incident_id,
            consolidated_text=consolidated_text,
            triage_severity_score=final_severity
        )
        retry_verifier_res = await verifier.run(retry_verifier_input)
        _update_state(retry_verifier_res)
        yield retry_verifier_res
        
        if not retry_verifier_res.result.agrees:
            logger.warning("Orchestrator: Verifier still disagrees after retry. Flagging for human review.")
            requires_human_review = True
            # We'll stick with the latest Triage score and move on
    
    # -----------------------------------------------------------------------
    # 4. Ambulance Classifier
    # -----------------------------------------------------------------------
    class_input = ambulance_classifier.ClassifierInput(
        incident_id=incident_input.incident_id,
        consolidated_text=consolidated_text,
        severity_score=final_severity
    )
    class_res = await ambulance_classifier.run(class_input)
    _update_state(class_res)
    yield class_res
    
    amb_type = class_res.result.ambulance_type
    req_equip = class_res.result.required_equipment

    # -----------------------------------------------------------------------
    # 5. Dispatch & Hospital Matcher (Concurrent)
    # -----------------------------------------------------------------------
    dispatch_in = dispatch.DispatchInput(
        incident_id=incident_input.incident_id,
        caller_location=caller_location,
        ambulance_type=amb_type,
        required_equipment=req_equip
    )
    
    matcher_in = hospital_matcher.MatcherInput(
        incident_id=incident_input.incident_id,
        caller_location=caller_location,
        consolidated_text=consolidated_text,
        severity_score=final_severity,
        ambulance_type=amb_type
    )
    
    dispatch_res, matcher_res = await asyncio.gather(
        dispatch.run(dispatch_in),
        hospital_matcher.run(matcher_in)
    )
    
    _update_state(dispatch_res)
    yield dispatch_res
    _update_state(matcher_res)
    yield matcher_res
    
    assigned_ambulance = dispatch_res.result.assigned_ambulance
    assigned_hospital = matcher_res.result.assigned_hospital

    # -----------------------------------------------------------------------
    # 6. Admission Formalities
    # -----------------------------------------------------------------------
    form_in = admission_formalities.FormalitiesInput(
        incident_id=incident_input.incident_id,
        consolidated_text=consolidated_text,
        patient_name=incident_input.caller_meta.name if incident_input.caller_meta else None,
        caller_phone=incident_input.caller_meta.phone if incident_input.caller_meta else None,
        severity_score=final_severity,
        ambulance=assigned_ambulance,
        hospital=assigned_hospital
    )
    form_res = await admission_formalities.run(form_in)
    _update_state(form_res)
    yield form_res

    # -----------------------------------------------------------------------
    # Assemble Final Output
    # -----------------------------------------------------------------------
    final_decision = FinalDecision(
        severity_score=final_severity,
        ambulance=assigned_ambulance,
        hospital=assigned_hospital,
        requires_human_review=requires_human_review
    )
    
    map_data = None
    if caller_location.lat is not None and caller_location.lng is not None:
        inc_loc = MapLocation(lat=caller_location.lat, lng=caller_location.lng)
        
        amb_obj = mock_store.get_ambulance(assigned_ambulance.ambulance_id)
        amb_loc = MapLocation(lat=amb_obj.lat, lng=amb_obj.lng) if amb_obj else inc_loc
        map_amb = MapAmbulance(
            id=assigned_ambulance.ambulance_id,
            current_location=amb_loc,
            eta_to_incident_minutes=assigned_ambulance.eta_minutes
        )
        
        hosp_obj = mock_store.get_hospital(assigned_hospital.hospital_id)
        hosp_loc = MapLocation(lat=hosp_obj.lat, lng=hosp_obj.lng) if hosp_obj else inc_loc
        
        eta_inc_to_hosp = None
        if hosp_obj and assigned_hospital.distance_km is not None:
            eta_inc_to_hosp = round((assigned_hospital.distance_km / 40.0) * 60, 1)
            
        map_hosp = MapHospital(
            id=assigned_hospital.hospital_id,
            location=hosp_loc,
            distance_from_incident_km=assigned_hospital.distance_km,
            eta_incident_to_hospital_minutes=eta_inc_to_hosp
        )
        
        map_data = MapData(
            incident_location=inc_loc,
            ambulance=map_amb,
            hospital=map_hosp
        )
    
    final_output = FinalOutput(
        incident_id=incident_input.incident_id,
        final_decision=final_decision,
        agent_trace=trace,
        hospital_admission_report=form_res.result.report,
        human_readable_brief=form_res.result.human_readable_brief,
        map_data=map_data
    )
    
    logger.info("Orchestrator: Pipeline complete for incident %s", incident_input.incident_id)
    yield final_output


async def process_incident(incident_input: IncidentInput) -> FinalOutput:
    """
    Backwards-compatible synchronous wrapper.
    Consumes the generator and returns the FinalOutput.
    """
    final = None
    async for event in process_incident_stream(incident_input):
        final = event
    
    if not isinstance(final, FinalOutput):
        raise RuntimeError("process_incident_stream did not yield FinalOutput last")
        
    return final
