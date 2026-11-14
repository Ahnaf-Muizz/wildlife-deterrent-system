#!/bin/bash
set -e

# ==============================================================================
# Jetson Orin Nano — Set IMX219 (8MP) specifically to CAM0 (connector J1)
# ECE 3332: Microcontroller Project Lab | Group 8
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo ">> Please run with sudo:"
    echo "   sudo ./set_cam0.sh"
    exit 1
fi

BASE_DTB="/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb"
OVERLAY="/boot/tegra234-p3767-camera-p3768-imx219-A.dtbo"
EXTLINUX="/boot/extlinux/extlinux.conf"

echo "=================================================================="
echo " Configuring Camera for CAM0 (Connector J1, CSI-A Port)"
echo " Overlay File: $OVERLAY"
echo "=================================================================="

# Ensure original DTB backup exists
if [ ! -f "${BASE_DTB}.orig" ]; then
    cp "$BASE_DTB" "${BASE_DTB}.orig"
fi

# Compile CAM0 overlay into DTB
echo ">> Merging CAM0 overlay into device tree..."
fdtoverlay -i "${BASE_DTB}.orig" -o "$BASE_DTB" "$OVERLAY"

if [ -f "/boot/$(basename "$BASE_DTB")" ]; then
    cp "$BASE_DTB" "/boot/$(basename "$BASE_DTB")"
fi

# Update extlinux.conf
echo ">> Updating $EXTLINUX..."
cat << EOF > "$EXTLINUX"
TIMEOUT 30
DEFAULT primary

MENU TITLE L4T boot options

LABEL primary
      MENU LABEL primary kernel
      LINUX /boot/Image
      FDT $BASE_DTB
      INITRD /boot/initrd
      APPEND \${cbootargs} root=PARTUUID=fa6264be-441f-46fd-96c3-282b3034b27e rw rootwait rootfstype=ext4 mminit_loglevel=4 console=ttyTCU0,115200 firmware_class.path=/etc/firmware fbcon=map:0 video=efifb:off console=tty0 efi_pstore.pstore_disable=1 pstore.backend=ramoops efi=runtime pci=pcie_bus_perf nvme.use_threaded_interrupts=1 swiotlb=2048
      OVERLAYS $OVERLAY
EOF

systemctl enable nvargus-daemon 2>/dev/null || true

echo ""
echo "=================================================================="
echo " [SUCCESS] CAM0 (Connector J1) Device Tree Activated!"
echo ""
echo " Reboot now:"
echo "   sudo reboot"
echo ""
echo " After reboot:"
echo "   python3 test_camera.py"
echo "=================================================================="
