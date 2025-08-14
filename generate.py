"""
.cur file structure

Notes:
- basically an .ico file but there is not .png support
  - images are stored in .bmp without the BITMAPHEADER
- numbers are stored in little endian

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
    16     4  biCompression    Not used, = 0
    20     4  biSizeImage      Image size in bytes (size of icColors + icAND)
    24     4  biXPelsPerMeter  Not used, = 0
    28     4  biYPelsPerMeter  Not used, = 0
    32     4  biClrUsed        Not used, = 0
    36     4  biClrImportant   Not used, = 0

.ani file structure

Notes:
- a RIFF file with many icons inside, each icon is a frame
  - these are normal icons: .png's are supported
- numbers are stored in little endian

Definitions:
- SEQUENCE = 0x2 // Flag which allows for a sequence of indices to be used (allows frames to be used multiple times)

1) RIFF chunk header
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'RIFF')
     4     4  chunkSize  Size of the chunk (except id and chunkSize = fileSize - 8)
     8     4  dataForm   Type of data contained (= 'ACON')

2) anih chunk
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'anih')
     4     4  chunkSize  Size of the chunk (except id and chunkSize = 36)
     8    36  aniHeader  Ani header

2.1) Ani header
Offset  Size  Name       Description
------------------------------------
     0     4  cbSizeof   Size of the header (= 36)
     4     4  cFrames    Number of frames in the list
     8     4  cSteps     Number of frames in the animation (the same as cFrames if not SEQUENCE is not set)
    12     4  cx         Not used, = 0
    16     4  cy         Not used, = 0
    20     4  cBitCount  Not used, = 0
    24     4  cPlanes    Not used, = 0
    28     4  jifRate    Default display rate in 1/60s (jiffies)
    32     4  flags      1's bit always set, optionally SEQUENCE

3) 'rate' and 'seq ' chunks when SEQUENCE is set

3.1) 'rate' chunk
Offset       Size  Name       Description
-----------------------------------------
     0          4  id         Chunk id (= 'rate')
     4          4  chunkSize  Size of the chunk (cFrames * 4)
     8  4*cFrames  rates      An array of jiffies for each image

3.2) 'seq ' chunk
Offset      Size  Name       Description
----------------------------------------
     0         4  id         Chunk id (= 'seq ', notice the space)
     4         4  chunkSize  Size of the chunk (cFrames * 4)
     8  4*cSteps  indices    An array of image indices to indicate what image to display on each frame

4) LIST chunk of frames
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'LIST')
     4     4  chunkSize  Size of the chunk (except id and chunkSize)
     8     4  listType   Type of the list (= 'fram')
    12     ?  iconData   Images of the animation (.ico files)

5) iconData

Like in .cur files this will contain a ICONDIR and multiple ICONDIRENTRY's.
The pixel data can either be in BMP format or in PNG format.
"""

# TODO: add support for .ani cursors

import os
import os.path
import shutil
import subprocess
import xml.etree.ElementTree as xml
from typing import Collection
from PIL import Image

# Utility functions
def u32(x: int) -> bytes: return x.to_bytes(4, "little")
def i32(x: int) -> bytes: return x.to_bytes(4, "little", signed=True)
def u16(x: int) -> bytes: return x.to_bytes(2, "little")
def u8(x: int) -> bytes: return x.to_bytes(1, "little")


class CursorGenerator:
    """
    CUR and ANI file generator, generates a cursor file from an SVG.

    The hotspot of the cursor is the top-left corner of the drawing by default.
    It can be changed by adding an object with the ID 'hotspot'. If such an
    object exists the hotspot will be at its top-left corner instead.

    Needs Inkscape. The name of the cursor is taken from the source file.
    The intermediate PNGs are store in 'png_out_dir/[cursor-name]/',
    named '[resolution].png'.
    """
    def __init__(self, src_svg: str, png_out_dir: str, cur_out_dir: str, res: Collection[int] = (32, 48, 64)):
        if src_svg[-4:] != ".svg":
            raise TypeError("expected an SVG image")
        if not os.path.exists(src_svg):
            raise FileNotFoundError(f"{src_svg} not found")

        self.src_svg = src_svg
        self.name = os.path.basename(self.src_svg)[:-4]
        self.png_out_dir = os.path.join(png_out_dir, self.name)
        self.cur_out_dir = cur_out_dir
        self.res = res
        self.is_animated = src_svg[-8:] == ".ani.svg"

    def __gen_pngs(self):
        print(f"Generating {self.name} PNGs...")
        src_file_mtime = os.path.getmtime(self.src_svg)

        os.makedirs(self.png_out_dir, exist_ok=True)

        actions = []
        out_files = []

        for res in self.res:
            out_file = os.path.join(self.png_out_dir, f"{res}.png")
            # Only generate the file if the SVG is newer than the PNG
            if os.path.exists(out_file) and os.path.getmtime(out_file) > src_file_mtime:
                print(f"    Skipped {out_file}")
                continue
            actions.extend([
                f"export-filename:{out_file}",
                f"export-width:{res}",
                f"export-height:{res}",
                "export-area-page",
                "export-do"
            ])
            out_files.append(out_file)

        if len(out_files) == 0:
            return

        print(f"    Generating {', '.join(out_files)}...")
        result = subprocess.run([
            "inkscape",
            "--without-gui",
            self.src_svg,
            '--actions=' + ";".join(actions)
        ], capture_output=True)
        if result.returncode != 0 or not all(map(os.path.exists, out_files)):
            exc = RuntimeError(f"Generation of {', '.join(out_files)} failed")
            exc.add_note("Stderr: " + result.stderr.decode())
            exc.add_note("Stdout: " + result.stdout.decode())
            raise exc

    def __gen_cur(self):
        print(f"Generating {self.name} CUR...")
        src_file_mtime = os.path.getmtime(self.src_svg)
        out_file = os.path.join(self.cur_out_dir, f"{self.name}.cur")
        # Only generate the file if the SVG is newer than the CUR
        if os.path.exists(out_file) and os.path.getmtime(out_file) > src_file_mtime:
            print(f"    Skipped {out_file}")
            return

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
        min_offset = len(icondir) + ENTRY_SIZE*len(self.res)
        x, y = self.__get_hotspot()
        for i, res in enumerate(self.res):
            hotspotX = int(res * x)
            hotspotY = int(res * y)
            image_offset = min_offset + sum(map(len, images[:i]))
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

        with open(out_file, "wb") as cur:
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
                pixel = image.getpixel((x, y))
                assert type(pixel) is tuple
                r, g, b, a = pixel
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

    def __get_hotspot(self) -> tuple[float, float]:
        """Get the hotspot where (0, 0) is top left and (1, 1) is bottom right"""
        svg_tree = xml.parse(self.src_svg).getroot()
        width = int(svg_tree.attrib["width"])
        height = int(svg_tree.attrib["height"])
        del svg_tree
        result = subprocess.run([
            "inkscape",
            self.src_svg,
            "--query-id=hotspot",  # If the object does not exist query the position of the drawing
            "-X", "-Y"  # Query x and y of the object
        ], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to query hotspot of {self.src_svg}")
        try:
            x, y = map(float, result.stdout.decode().split("\n", maxsplit=1))
        except Exception as e:
            e.add_note(f"Failed to query hotspot of {self.src_svg}")
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
