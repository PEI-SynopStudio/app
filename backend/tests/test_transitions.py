import pytest
import itertools

from app.core.exceptions import InvalidStateTransitionError
from app.schemas.enums import JobStatusEnum
from app.services.workflow import transitions

TERMINAL_STATUS = (JobStatusEnum.COMPLETED, JobStatusEnum.FAILED, JobStatusEnum.CANCELLED)

VALID_TRANSITIONS = {
    (JobStatusEnum.PENDING, JobStatusEnum.QUEUED),
    (JobStatusEnum.PENDING, JobStatusEnum.FAILED),
    (JobStatusEnum.PENDING, JobStatusEnum.CANCELLED),
    (JobStatusEnum.QUEUED, JobStatusEnum.PROCESSING),
    (JobStatusEnum.QUEUED, JobStatusEnum.FAILED),
    (JobStatusEnum.QUEUED, JobStatusEnum.CANCELLED),
    (JobStatusEnum.PROCESSING, JobStatusEnum.COMPLETED),
    (JobStatusEnum.PROCESSING, JobStatusEnum.FAILED),
    (JobStatusEnum.PROCESSING, JobStatusEnum.CANCELLED),
}

ALL_PAIRS = list(itertools.product(JobStatusEnum, JobStatusEnum))
INVALID_TRANSITIONS = [pair for pair in ALL_PAIRS if pair not in VALID_TRANSITIONS]

# Test final status

def test_final_statuses_have_no_transitions():
    for status in TERMINAL_STATUS:
        assert transitions.final_state(status) is True
        for target in JobStatusEnum:
            if target != status:
                assert transitions.can_transition(status, target) is False
        
def test_nonfinalstatus():
    for status in (JobStatusEnum.PENDING, JobStatusEnum.QUEUED, JobStatusEnum.PROCESSING):
        assert transitions.final_state(status) is False

        
def test_final_statuses_raise_exception_on_transition():
    for status in TERMINAL_STATUS:
        with pytest.raises(InvalidStateTransitionError):
            transitions.validate_transition(status, JobStatusEnum.PENDING)
            
            
# test valid and invalid transitions   
def test_valid_transitions():
    for status, target in VALID_TRANSITIONS:
        assert transitions.can_transition(status, target) is True
        assert transitions.validate_transition(status, target) is None
            
            
def test_invalid_transitions():
    for status, target in INVALID_TRANSITIONS:
        assert transitions.can_transition(status, target) is False
        with pytest.raises(InvalidStateTransitionError):
            transitions.validate_transition(status, target)


def test_transition_to_same_status():
    for status in JobStatusEnum:
        with pytest.raises(InvalidStateTransitionError):
            transitions.validate_transition(status, status)
        assert transitions.can_transition(status, status) is False
            
         
def test_transition_from_none_status():
    with pytest.raises(InvalidStateTransitionError):
        transitions.validate_transition(None, JobStatusEnum.PENDING)
        
def test_transition_to_none_status():
    with pytest.raises(InvalidStateTransitionError):
        transitions.validate_transition(JobStatusEnum.PENDING, None)
        

# Specific transition tests
def test_queuedtransition():
    assert transitions.can_transition(JobStatusEnum.QUEUED, JobStatusEnum.PROCESSING) is True
    assert transitions.can_transition(JobStatusEnum.QUEUED, JobStatusEnum.COMPLETED) is False
    assert transitions.can_transition(JobStatusEnum.QUEUED, JobStatusEnum.PENDING) is False
    
def test_pending_transition():
    assert transitions.can_transition(JobStatusEnum.PENDING, JobStatusEnum.QUEUED) is True
    assert transitions.can_transition(JobStatusEnum.PENDING, JobStatusEnum.PROCESSING) is False
    assert transitions.can_transition(JobStatusEnum.PENDING, JobStatusEnum.COMPLETED) is False
    assert transitions.can_transition(JobStatusEnum.PENDING, JobStatusEnum.FAILED) is True
    assert transitions.can_transition(JobStatusEnum.PENDING, JobStatusEnum.CANCELLED) is True
    
def test_processing_transition():
    assert transitions.can_transition(JobStatusEnum.PROCESSING, JobStatusEnum.COMPLETED) is True
    assert transitions.can_transition(JobStatusEnum.PROCESSING, JobStatusEnum.FAILED) is True
    assert transitions.can_transition(JobStatusEnum.PROCESSING, JobStatusEnum.CANCELLED) is True
    assert transitions.can_transition(JobStatusEnum.PROCESSING, JobStatusEnum.PENDING) is False
    assert transitions.can_transition(JobStatusEnum.PROCESSING, JobStatusEnum.QUEUED) is False