package com.agentservice.ticket;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class TicketStateMachineTest {

    @Test
    void newCanGoToProcessing() {
        assertTrue(TicketStateMachine.canTransition(TicketStatus.NEW, TicketStatus.PROCESSING));
    }

    @Test
    void timeoutCanEscalateToEscalated() {
        assertTrue(TicketStateMachine.canTransition(TicketStatus.NEW, TicketStatus.ESCALATED));
        assertTrue(TicketStateMachine.canTransition(TicketStatus.PROCESSING, TicketStatus.ESCALATED));
        assertDoesNotThrow(() ->
                TicketStateMachine.requireTransition(TicketStatus.PROCESSING, TicketStatus.ESCALATED));
    }

    @Test
    void escalatedCanBeClosedByHuman() {
        assertTrue(TicketStateMachine.canTransition(TicketStatus.ESCALATED, TicketStatus.CLOSED));
        assertTrue(TicketStateMachine.canTransition(TicketStatus.ESCALATED, TicketStatus.RESOLVED));
        assertDoesNotThrow(() ->
                TicketStateMachine.requireTransition(TicketStatus.ESCALATED, TicketStatus.RESOLVED));
    }

    @Test
    void illegalJumpReturnsConflict() {
        assertFalse(TicketStateMachine.canTransition(TicketStatus.NEW, TicketStatus.REFUNDED));
        assertThrows(IllegalTransitionException.class,
                () -> TicketStateMachine.requireTransition(TicketStatus.NEW, TicketStatus.REFUNDED));
    }

    @Test
    void fullHappyFlowNewToClosed() {
        assertDoesNotThrow(() -> {
            TicketStateMachine.requireTransition(TicketStatus.NEW, TicketStatus.PROCESSING);
            TicketStateMachine.requireTransition(TicketStatus.PROCESSING, TicketStatus.RESOLVED);
            TicketStateMachine.requireTransition(TicketStatus.RESOLVED, TicketStatus.CLOSED);
        });
    }

    @Test
    void terminalStatesAreFinal() {
        assertFalse(TicketStateMachine.canTransition(TicketStatus.CLOSED, TicketStatus.PROCESSING));
        assertFalse(TicketStateMachine.canTransition(TicketStatus.REFUNDED, TicketStatus.NEW));
        assertFalse(TicketStateMachine.canTransition(TicketStatus.ESCALATED, TicketStatus.NEW));
    }
}
