---
name: Bug report
about: Report unexpected behaviour or a defect in Autoheal
title: ""
labels: bug
assignees: ""
---

## Describe the bug

A clear, concise description of what went wrong.

## Expected behaviour

What did you expect to happen?

## Actual behaviour

What actually happened instead?

## Steps to reproduce

1.
2.
3.

## Environment

- Autoheal version/image tag:
- Docker version (`docker version`):
- Host OS:
- Deployment method (docker run / docker-compose / other):

## Relevant configuration

Autoheal environment variables / config relevant to the issue (redact secrets):

```
AUTOHEAL_INTERVAL=
AUTOHEAL_LOG_LEVEL=
...
```

## Affected container(s) and health status

Container name/image, and output of `docker inspect --format='{{json .State.Health}}' <container>` if applicable.

## Relevant logs

Autoheal logs around the time of the issue (redact secrets/sensitive data):

```
paste logs here
```

## Additional context

Anything else that might help diagnose the issue.
