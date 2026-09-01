# A5 Message Hub

## Responsible Nodes
- N018 / S3 / S3 消息中台

## Responsibilities
- owner message
- operator message
- frontdesk message
- daily report
- alert
- approval card

## Forbidden Actions
- leak source code
- leak config
- leak secrets
- export row-level order detail

## Demo Mode Boundary
- Demo inputs are allowed only when marked `data_source_type=demo_data` and `freshness_status=demo_data`.
- Demo outputs must set `approval_data_allowed=false` and `live_allowed=false`.
- Demo results must not be described as today's real business facts.
