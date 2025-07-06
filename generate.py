import os
import os.path
import shutil
import subprocess
import xml.etree.ElementTree as xml
from typing import Iterable
from PIL import Image

# Utility functions
def u32(x: int) -> bytes: return x.to_bytes(4, "little")
def i32(x: int) -> bytes: return x.to_bytes(4, "little", signed=True)
def u16(x: int) -> bytes: return x.to_bytes(2, "little")
def u8(x: int) -> bytes: return x.to_bytes(1, "little")


class CursorGenerator:
    """
    CUR file generator, generates a cursor file from an SVG.

    The hotspot of the cursor is the top-left corner of the drawing by default.
    It can be changed by adding an object with the ID 'hotspot'. If such an
    object exists the hotspot will be at its top-left corner instead.

    Needs Inkscape. The name of the cursor is taken from the source file.
    The intermediate PNGs are store in 'png_out_dir/[cursor-name]/',
    named '[resolution].png'.
    """
    def __init__(self, src_svg: str, png_out_dir: str, cur_out_dir: str, res: Iterable[int] = (32, 48, 64)):
        if src_svg[-4:] != ".svg":
            raise TypeError("expected an SVG image")
        if not os.path.exists(src_svg):
            raise FileNotFoundError(f"{src_svg} not found")

        self.src_svg = src_svg
        self.name = os.path.basename(self.src_svg)[:-4]
        self.png_out_dir = os.path.join(png_out_dir, self.name)
        self.cur_out_dir = cur_out_dir
        self.res = res

    def __gen_pngs(self):
        print(f"Generating {self.name} PNGs...")
        src_file_mtime = os.path.getmtime(self.src_svg)

        os.makedirs(self.png_out_dir, exist_ok=True)

        for res in self.res:
            out_file = os.path.join(self.png_out_dir, f"{res}.png")
            if os.path.exists(out_file) and os.path.getmtime(out_file) > src_file_mtime:
                print(f"    Skipped {out_file}")
                continue
            print(f"   Generating {out_file}...")

            result = subprocess.run([
                "inkscape",
                self.src_svg,
                "--export-area-page",
                "--export-overwrite",
                f"--export-filename={out_file}",
                f"--export-width={res}",
                f"--export-height={res}",
            ], capture_output=True)
            if result.returncode != 0:
                exc = RuntimeError(f"Generation of {out_file} failed")
                exc.add_node(result.stderr.decode())
                raise exc
            if not os.path.exists(out_file):
                raise RuntimeError(f"GenGeneration of {out_file} failedd")

    def __gen_cur(self):
        """
        File structure (numbers are store in little endian)

        1) ICONDIR
        Offset  Size  Name        Description
        -------------------------------------
             0     2  idReserved  Always 0
             2     2  idType      Always 2 (1 specifies .ico files)
             4     2  idCount     Number of images in the file

        2) ICONDIRENTRY * idCount
        Offset  Size  Name           Description
        ----------------------------------------
             0     1  bWidth         Image width (0 becomes 256)
             1     1  bHeight        Image height (0 becomes 256)
             2     1  bColorCount    Number of colors in palette (0 if not used and if >= 8bpp)
             3     1  bReserved      Always 0
             4     2  wPlanes        Cursor hotspot X (pixels from the left)
             6     2  wBitCount      Cursor hotspot Y (pixels from the top)
             8     4  dwBytesInRes   Number of bytes in the pixel data
            12     4  dwImageOffset  Offset from the beginning of the file of the pixel data

        3) Image pixel data in BMP format
        Name      Description
        ---------------------
        icHeader  DIB header
        icColors  Image colors in BGRA format
        icXOR     Empty
        icAND     Bit mask: 1 = transparent pixel, 0 = use color

        3.1) BITMAPINFOHEADER
        Offset  Size  Name             Descritpion
        ------------------------------------------
             0     4  biSize           Header size (= 40)
             4     4  biWidth          Image width in pixels
             8     4  biHeight         Image height in pixels * 2
            12     2  biPlanes         = 1
            14     2  biBitCount       = 32
            16     4  biCompression    Unused, = 0
            20     4  biSizeImage      Image size in bytes (size of icColors + icAND)
            24     4  biXPelsPerMeter  Unused, = 0
            28     4  biYPelsPerMeter  Unused, = 0
            32     4  biClrUsed        Unused, = 0
            36     4  biClrImportant   Unused, = 0
        """

        print(f"Generating {self.name} CUR...")
        icondir = bytearray()
        icondir.extend((0).to_bytes(2, "little"))
        icondir.extend((2).to_bytes(2, "little"))
        icondir.extend(len(self.res).to_bytes(2, "little"))

        images = []
        for res in self.res:
            png = os.path.join(self.png_out_dir, f"{res}.png")
            images.append(self.__gen_bitmap(png, res))

        entries = []
        ENTRY_SIZE = 16
        x, y = self.__get_hotspot()
        for i, res in enumerate(self.res):
            hotspotX = int(res * x)
            hotspotY = int(res * y)
            image_offset = len(icondir) + ENTRY_SIZE * len(self.res) + sum(map(len, images[:i]))
            entry = bytearray()
            entry.extend(u8(res))              # bWidth
            entry.extend(u8(res))              # bHeight
            entry.extend(u8(0))                # bColorCount
            entry.extend(u8(0))                # bReserved
            entry.extend(u16(hotspotX))        # wPlanes (hotspotX)
            entry.extend(u16(hotspotY))        # wBitCount (hotspotY)
            entry.extend(u32(len(images[i])))  # dwBytesInRes
            entry.extend(u32(image_offset))    # dwImageOffset
            entries.append(entry)

        os.makedirs(self.cur_out_dir, exist_ok=True)

        with open(os.path.join(self.cur_out_dir, f"{self.name}.cur"), "wb") as cur:
            cur.write(icondir)
            for entry in entries:
                cur.write(entry)
            for image in images:
                cur.write(image)

    @staticmethod
    def __gen_bitmap(img_path: str, res: int) -> bytearray:
        image = Image.open(img_path)
        image = image.convert("RGBA")
        assert image.width == res and image.height == res

        bgra_table_size = res * res * 4
        if res * res % 8 == 0:
            and_mask_size = res * res // 8
        else:
            and_mask_size = res * res // 8 + 1
        and_mask_size += and_mask_size & 1  # make image_size even (to end at a WORD boundary)

        image_size = bgra_table_size + and_mask_size

        image_data = bytearray()

        # BITMAPINFOHEADER
        image_data.extend(u32(40))               # biSize
        image_data.extend(i32(image.width))      # biWidth
        image_data.extend(i32(image.height * 2)) # biHeight
        image_data.extend(u16(1))                # biPlanes
        image_data.extend(u16(32))               # biBitCount
        image_data.extend(u32(0))                # biCompression
        image_data.extend(u32(image_size))       # biImageSize
        image_data.extend(u32(0))                # biXPelsPerMeter
        image_data.extend(u32(0))                # biYPelsPerMeter
        image_data.extend(u32(0))                # biClrUsed
        image_data.extend(u32(0))                # biClrImportant

        # Pixel colors (row by row from bottom to top and left to right)
        mask = ""
        for y in range(res - 1, -1, -1):
            for x in range(res):
                r, g, b, a = image.getpixel((x, y))
                if a == 0:
                    r = g = b = 0
                    mask += "1"
                else:
                    mask += "0"
                image_data.extend(u8(b))
                image_data.extend(u8(g))
                image_data.extend(u8(r))
                image_data.extend(u8(a))
        del image
        mask += "0" * (len(mask) - and_mask_size * 8)

        # Add the AND mask
        for mask_byte in range(and_mask_size):
            byte = mask[mask_byte * 8:(mask_byte+1) * 8]
            byte = int(byte, 2)
            image_data.extend(u8(byte))

        return image_data

    def __get_hotspot(self) -> tuple[int, int]:
        svg_tree = xml.parse(self.src_svg).getroot()
        width = int(svg_tree.attrib["width"])
        height = int(svg_tree.attrib["height"])
        del svg_tree
        result = subprocess.run([
            "inkscape",
            self.src_svg,
            "--query-id=hotspot",
            "-X", "-Y"
        ], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to query hotspot of {self.src_svg}")
        try:
            x, y = map(float, result.stdout.decode().split("\n", maxsplit=1))
        except Exception as e:
            e.add_node(f"Failed to query hotspot of {self.src_svg}")
            raise e

        x /= width
        y /= height

        return min(max(x, 0), 1), min(max(y, 0), 1)

    def generate(self):
        self.__gen_pngs()
        self.__gen_cur()


def main():
    if shutil.which("inkscape") is None:
        print("Inkscape is required to use generate.py")

    for file in os.listdir("svgs"):
        generator = CursorGenerator(os.path.abspath(os.path.join("svgs", file)), "pngs", "cursors", res=(32, 48, 64))
        generator.generate()


if __name__ == "__main__":
    main()
