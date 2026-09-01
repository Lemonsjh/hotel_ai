# User Context

The operator expects deployment-safe behavior:

- Do not write generated reports into the git repository.
- Do not overwrite reports from previous hotels or runs.
- Use port 8081 for the public report URL on the current server unless the environment says otherwise.
- Prefer explicit commands and report exact paths.
