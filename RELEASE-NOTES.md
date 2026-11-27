# Wired field console R3.4 RC4

On a paired direct USB screen with burst support, the Pi can send one exact RGB565 rectangle when a short label crosses tile boundaries. It chooses that rectangle only if it requires fewer USB exchanges, keeps the data volume within the previous plan, and preserves the response time for an interaction near the pointer.

In projected 800×600 synthetic desktop fixtures, changing one temperature digit took two exchanges in both versions. A state-label change took three exchanges, down from four. Replacing the pinned label took five, down from nine. Replaying the accepted commands reproduced the target pixels exactly. These counts describe the sender plan and its acknowledgements.

The existing pointer counter now advances as soon as the final cursor rectangle is acknowledged, including when the desktop changes in the same captured frame. The reported duration covers planning through that acknowledgement. It contains no coordinates. The update uses the existing screen application, owner checks and enrollment.

See **UPGRADE.md** for the offline installation check and rollback. [Matched RC3 release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc3)
