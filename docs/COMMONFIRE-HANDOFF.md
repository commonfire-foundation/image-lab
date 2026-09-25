# Handoff: intended release under CommonFIRE

## Decision and scope

The project owner has expressed the intent to release Image Lab under the **CommonFIRE** GitHub organization, `commonfire-foundation`, rather than as an exclusively OldJobobo-owned project.

**OldJobobo should remain prominently credited as Image Lab's creator and maintainer.** The intended arrangement is:

- **CommonFIRE:** the shared project home and mission.
- **OldJobobo:** the identifiable creator and maintainer.
- **Image Lab:** a concrete, useful application demonstrating the mission.

Promotion through OldJobobo's personal profile and channels can help people discover CommonFIRE through the tool itself. Lead Image Lab's public description with what it does; explain the organizational connection afterward.

The owner chose an MIT release under CommonFIRE and confirmed the Image Lab
repository address. A **private, empty** organization repository has been created
and configured as this checkout's `origin`; no source has been pushed and no
release has been published. Imagescope stays a separate project.

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

- [x] Create the private, empty Image Lab repository under CommonFIRE and add its Git remote. No commits, tags, or assets have been pushed.
- [x] Add the owner-approved MIT license to the repository and package metadata, crediting OldJobobo as creator.
- [x] Prepare a user-local release-bundle installer; the old RC1 development-snapshot candidate is superseded.
- [x] Imagescope `v0.1.0rc2` is a published prerelease at commit `333cd17`. The old RC1 public wheel lacks APIs Image Lab needs. Use the published RC2 wheel and source archive, not a relabelled development snapshot. Image Lab publication requires fresh acceptance with those exact artifacts.
- [ ] Review source and release contents for personal paths, private data, and image rights. Do not blindly publish local `results/`, catalogs, caches, or development artifacts.
- [ ] Update public documentation and package metadata with the confirmed repository, creator/maintainer credit, installation instructions, and a concise CommonFIRE connection.
- [ ] Run the relevant test and installed-package checks, and state supported platforms and remaining limitations accurately.
- [ ] Feature Image Lab on the organization profile when publication is ready. Organization profile content belongs in the public `commonfire-foundation/.github` repository at `profile/README.md`.

## Zero-cost constraint

The owner's current goal is **$0 spending**. Keep the organization on GitHub Free, avoid paid services and larger runners, and verify applicable billing controls before enabling automation. Standard hosted runner execution for public repositories is free, but storage, other GitHub products, and external services have their own rules.

No GitHub settings or spending controls have been verified or changed as part of this handoff.

## Organization

Internal planning records are maintained separately and are not part of this release.

Organization:
https://github.com/commonfire-foundation

Image Lab repository:
https://github.com/commonfire-foundation/image-lab
