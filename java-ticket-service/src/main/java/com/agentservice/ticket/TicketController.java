package com.agentservice.ticket;

import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 工单 REST 接口。非法跳转返回 409（{detail}），不存在返回 404。 */
@RestController
@RequestMapping("/tickets")
public class TicketController {
    private final TicketService service;

    public TicketController(TicketService service) {
        this.service = service;
    }

    public record CreateTicketRequest(String sessionId, String title, String category, String priority) {
    }

    public record TransitionRequest(TicketStatus to) {
    }

    @GetMapping
    public List<Ticket> list(@RequestParam(required = false) String sessionId) {
        return service.list(sessionId);
    }

    @PostMapping
    public ResponseEntity<Ticket> create(@RequestBody CreateTicketRequest req) {
        Ticket ticket = service.create(
                req.sessionId() == null ? "" : req.sessionId(),
                req.title() == null ? "未命名工单" : req.title(),
                req.category() == null ? "general" : req.category(),
                req.priority() == null ? "normal" : req.priority());
        return ResponseEntity.status(HttpStatus.CREATED).body(ticket);
    }

    @GetMapping("/{id}")
    public Ticket get(@PathVariable long id) {
        return service.get(id).orElseThrow(() -> new IllegalArgumentException("工单不存在: " + id));
    }

    @PostMapping("/{id}/transition")
    public Ticket transition(@PathVariable long id, @RequestBody TransitionRequest req) {
        return service.transition(id, req.to());
    }

    @GetMapping("/overdue")
    public List<Ticket> overdue() {
        return service.overdue();
    }

    @ExceptionHandler(IllegalTransitionException.class)
    public ResponseEntity<Map<String, String>> handleIllegalTransition(IllegalTransitionException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("detail", e.getMessage()));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleNotFound(IllegalArgumentException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("detail", e.getMessage()));
    }
}
