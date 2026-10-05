# aws-cicd-lab

My hands-on learning ci/cd, Git, docker and AWS.



\## Project goal



Build a small application with automated testing and deployment to AWS.



\## Learning checklist



\- \[ ] Practise Git branches and pull requests

\- \[ ] Build and test a small application

\- \[ ] Package the application with Docker

\- \[ ] Automate testing with GitHub Actions

\- \[ ] Deploy to AWS

\- \[ ] Demonstrate rollback


## CI failure and recovery exercise

In [PR #5](https://github.com/yongkang863/aws-cicd-lab/pull/5),
I deliberately changed the homepage title to demonstrate CI catching a mistake.

- The automated homepage test failed.
- The Docker build step was skipped.
- Branch protection requires the "Test and build" check to pass before merging.

The correction restores the expected homepage title.
Pushing the correction to the same branch triggers another CI run.
