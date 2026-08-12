# Brand fonts

Drop these three files here:

- `Inter-Black.ttf`
- `Inter-Bold.ttf`
- `Inter-Regular.ttf`

Inter is free under the SIL Open Font License: https://rsms.me/inter/

Without them the renderer falls back to a system face (DejaVu / Liberation /
Helvetica / Arial, whichever it finds) and logs a warning once per run. Output
stays legible, but default type is most of what makes an account look
generic — this is a fifteen-minute job with a disproportionate payoff.

Any other family works. Point `fonts:` in `config/brand.yaml` at it.
