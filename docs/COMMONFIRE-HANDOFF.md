# Handoff: intended release under CommonFIRE

## Decision and scope

The project owner has expressed the intent to release Image Lab under the **CommonFIRE** GitHub organization, `commonfire-foundation`, rather than as an exclusively OldJobobo-owned project.

**OldJobobo should remain prominently credited as Image Lab's creator and maintainer.** The intended arrangement is:

- **CommonFIRE:** the shared project home and mission.
- **OldJobobo:** the identifiable creator and maintainer.
- **Image Lab:** a concrete, useful application demonstrating the mission.

Promotion through OldJobobo's personal profile and channels can help people discover CommonFIRE through the tool itself. Lead Image Lab's public description with what it does; explain the organizational connection afterward.

This records release intent, not a completed publication, repository transfer, or authorization to change remote repositories or billing. The final repository name, release timing, and Imagescope's ownership remain undecided.

## Why Image Lab fits

CommonFIRE stands for **Free Intelligence, Research and Evolution**. Its mission includes powerful, freely available AI, affordable compute, efficient tools for everyday hardware, open research, and independence from any single provider.

Image Lab offers a practical expression of that mission:

- A local desktop image catalog, contact sheet, search, and on-demand AI tagging.
- A separate Imagescope analysis backend rather than analysis inseparable from the GUI.
- Resource-conscious implementation, including software rendering by default so browsing does not compete with inference for the GPU.
- Local automation through a private Unix-socket interface.
- Documented experiments, evaluation limitations, and safeguards for original files.

Wallpaper analysis and organization are the initial application, not the limits of CommonFIRE's mission. Image Lab can be its first useful tool without defining the organization's entire future direction.

These points were grounded in a read-only review of `README.md`, `EVALUATION.md`, `pyproject.toml`, and `image_lab_ui/analyzer_client.py`. No fresh tests, live inference, or release-readiness audit were performed for this handoff. Historical evaluation results should not be presented as new verification or broad hardware/accuracy guarantees.

## Before public release

- [ ] Confirm the destination repository under `commonfire-foundation` and whether this is a new publication or a transfer.
- [ ] Choose and add an explicit project license. No root license file was present during the review; do not infer a license from organizational intent.
- [ ] Make installation practical for users outside the development workspace. Image Lab currently pins the separate `imagescope==0.1.0` dependency, which its README describes as unpublished on PyPI.
- [ ] Coordinate compatible Imagescope distribution without assuming that Imagescope must also move to CommonFIRE.
- [ ] Review source and release contents for personal paths, private data, and image rights. Do not blindly publish local `results/`, catalogs, caches, or development artifacts.
- [ ] Update public documentation and package metadata with the confirmed repository, creator/maintainer credit, installation instructions, and a concise CommonFIRE connection.
- [ ] Run the relevant test and installed-package checks, and state supported platforms and remaining limitations accurately.
- [ ] Feature Image Lab on the organization profile when publication is ready. Organization profile content belongs in the public `commonfire-foundation/.github` repository at `profile/README.md`.

## Zero-cost constraint

The owner's current goal is **$0 spending**. Keep the organization on GitHub Free, avoid paid services and larger runners, and verify applicable billing controls before enabling automation. Standard hosted runner execution for public repositories is free, but storage, other GitHub products, and external services have their own rules.

No GitHub settings or spending controls have been verified or changed as part of this handoff.

## Related planning workspace

The local CommonFIRE planning documents are in:

`/home/oldjobobo/Projects/commonfire/`

- `MISSION.md` — mission statement and organization description.
- `VISION.md` — founding vision and commitments.
- `GITHUB-FREE-GUIDE.md` — free allowances, zero-spend setup checklist, and official references.
- `README.md` — workspace overview.

That workspace is separate from Image Lab; this handoff does not authorize edits there.

Organization:
https://github.com/commonfire-foundation
