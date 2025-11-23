# ChatGPT Bots for Rising Storm 2: Vietnam

[![Coverage Status](https://tuokri.github.io/RS2ChatGPTBots/coverage-badge.svg)](https://tuokri.github.io/RS2ChatGPTBots/cov_html/index.html)

---

Provides a way for Rising Storm 2: Vietnam players to communicate
via text with in-game "bots" that are powered by OpenAI's LLMs.

## Technical details

This project contains two parts, the `ChatGPTBotsMutator` mutator for RS2
dedicated servers, and a Python "proxy" server that allows the mutator to
communicate with OpenAI APIs.

## Dependencies

The project depends on the `LibHTTP.u` package from https://github.com/tuokri/ue3-libhttp.
It is required by the `ChatGPTBots.u` mutator code for RS2 dedicated servers.
The Steam Workshop distribution of this mod includes all the UnrealScript dependencies.

## Deployment

Deploying the Python `chatgpt_proxy` proxy server requires a Postgres database and a Redis
instance.

## TODO

Remember to build a server-only version of LibHTTP for all SWS/GitHub releases!

Logging setup for production deployment!
