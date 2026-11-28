# Orange Pi sender for the matched RC6 display

- Reuse unchanged pixels in supported 2:1 desktop capture.
- Wake capture on desktop pointer events and retain periodic sampling.
- Limit dirty-tile searches to changed regions and retain accepted touch sequences.
- Find the scene's changed bounds before examining compressed tiles.
- Check for a newer guarded cursor after a completed pointer plan and after eligible erase acknowledgements.
