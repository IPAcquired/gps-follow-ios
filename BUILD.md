# Build the CORVON743V2 firmware

Use a Linux shell with Git, GNU Make, Python 3, ArduPilot's Linux build prerequisites, and the Arm GNU Embedded Toolchain on `PATH`. The release build used Python 3.14.4 and `arm-none-eabi-g++` 10.2.1 from the 10-2020-q4-major toolchain. The pinned upstream checkout includes the prerequisite installer at `Tools/environment_install/install-prereqs-ubuntu.sh`. [ArduPilot Linux setup](https://ardupilot.org/dev/docs/building-setup-linux.html)

Start in the directory containing this document and the patch. The following commands verify the patch and upstream source, fetch the dependency revisions recorded by Git, then build the firmware.

```sh
set -eu
release_dir=$(pwd -P)
printf '%s  %s\n' e03408e5f6d1c8838403f0a31ccc38529a424e37c24d730ef2d983bb1da5d8ce complete-source.patch | sha256sum -c -

git clone --branch Copter-4.7.3 --depth 1 https://github.com/ArduPilot/ardupilot.git ardupilot-build
cd ardupilot-build
test "$(git rev-parse HEAD)" = d9c5097c3d8333435712ffed86bca8ce00c4bb46
git submodule update --init --recursive
git submodule status --recursive
git apply --check "$release_dir/complete-source.patch"
git apply "$release_dir/complete-source.patch"
./waf configure --board CORVON743V2 --no-submodule-update
./waf -j6 copter
```

The resulting firmware package is `build/CORVON743V2/bin/arducopter.apj`. The form used by the bootloader is the image inside that package. Build metadata and the build environment can affect package bytes. The explicit source and toolchain revisions identify the inputs for rebuilding.

For a software-in-the-loop build of the same changes, run `./waf configure --board sitl --no-submodule-update` followed by `./waf -j6 copter` from the same patched checkout.
