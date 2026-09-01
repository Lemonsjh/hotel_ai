## ADDED Requirements

### Requirement: Public review body fields must remain readable

The runtime MUST NOT mask public OTA review body fields as whole values.

#### Scenario: Profile asks to redact review text

- **WHEN** a row contains `review_text`, `review_content`, `comment_content`, or `comment`
- **AND** profile privacy settings include those fields in `redact_fields`
- **THEN** those public review body values remain readable
- **AND** private fields in the same row remain redacted

### Requirement: Private review-adjacent fields remain protected

Private customer, order, room, operator, and product cipher fields MUST remain redacted.

#### Scenario: Review row contains private fields

- **WHEN** a review row contains `guest_name`, `phone`, `id_card`, `order_id`, `room_no`, `operator_name`, or `product_cipher`
- **THEN** those fields are masked or removed according to existing runtime rules
