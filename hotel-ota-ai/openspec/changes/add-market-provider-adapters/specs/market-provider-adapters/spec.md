## ADDED Requirements

### Requirement: External market inputs expose quality and cannot trigger direct price changes
Weather and event results MUST include source, capture time, freshness and field quality. Search-derived events MUST be marked partial and MUST NOT independently authorize price changes.

#### Scenario: Activity search returns a candidate
- **WHEN** an activity provider returns a verified URL but inferred attendance impact
- **THEN** S4 marks the result `search_inferred` and S5 can only lower confidence or add a review recommendation
