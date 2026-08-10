## ADDED Requirements

### Requirement: Completion-uncertain recovery retains authoritative mutation identity

For every mutation call, the MCP application and server SHALL share one
request-scoped execution context. Once Controller dispatch returns a task identity,
the context SHALL retain it through cancellation-after-return, result-size checks,
nested current-action validation, result-envelope construction and validation,
unexpected exceptions, and the server outer output guard.

If completion may have occurred, the error SHALL be `MCP_COMPLETION_UNCERTAIN`, its
details and read-after-write recovery SHALL contain the authoritative task ID, its
recovery tool SHALL be executable with that ID, and `blind_retry` SHALL be false.
Automatic task-ID generation SHALL remain supported.

#### Scenario: Automatic task creation succeeds but application post-processing fails

- **WHEN** Controller creates a task without a caller-supplied ID and an application result limit, validation, envelope, or unexpected failure occurs afterward
- **THEN** the uncertain response identifies the generated task and `dev_flow_get_task` can execute directly from its recovery object

#### Scenario: The server outer guard rejects the generated result

- **WHEN** Controller created an automatically identified task but the server rejects the final structured output
- **THEN** the outer error retains that task ID, forbids blind retry, and does not direct the caller to repeat task creation
