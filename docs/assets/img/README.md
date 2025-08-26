# Assets Directory

This directory contains images and media files for the Chirpy theme.

## Directory Structure

- `commons/`: Common images like avatars, logos
- `favicons/`: Favicon files for different sizes and formats
- `posts/`: Images used in blog posts

## Image Guidelines

- **Avatar**: 200x200px recommended, stored as `commons/avatar.jpg`
- **Favicons**: Multiple sizes (16x16, 32x32, etc.) stored in `favicons/`
- **Post Images**: Store in `posts/` directory with descriptive names

## Usage

Reference images in markdown using:
```markdown
![Alt text]({{ site.baseurl }}/assets/img/path/to/image.jpg)
```

Or for avatars and favicons, configure in `_config.yml`:
```yaml
avatar: /assets/img/commons/avatar.jpg
favicon: /assets/img/favicons/
```
