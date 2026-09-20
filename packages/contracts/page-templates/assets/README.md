# Demonstration photographs

These four images were generated with OpenAI imagegen on 2026-09-20 for the
Site Studio template library. They depict fictional example settings, not
customer premises, equipment or animals. No customer or stock-service files
were used as references. They are editable starter content, not evidence of a
business offering a service or owning the pictured location.

- `business-studio.png`: bright meeting studio with a laptop, oak table and plants.
- `medicine-room.png`: empty consultation room with an examination chair.
- `agriculture-farm.png`: dairy cows grazing near a barn.
- `electronics-workshop.png`: circuit board and diagnostic equipment.

Canonical filenames and SHA-256 digests are in `../sample-media.v1.json`.
The frontend imports these exact local assets for catalogue previews. Applying
a template copies the selected image through the ordinary tenant media
lifecycle (quota, upload completion, scan, normalization and variants).
Published pages reference the resulting tenant asset, never this catalogue.
