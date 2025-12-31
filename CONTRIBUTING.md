# Contributing to Stagg EKG+ Home Assistant Integration

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## How to Contribute

### Reporting Issues

If you find a bug or have a feature request:

1. Check if the issue already exists in the [Issues](https://github.com/rderewianko/fellow-ekg/issues) section
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Your Home Assistant version
   - Kettle firmware version (from `stagg_ekg_api.py` or integration logs)
   - Relevant logs or error messages

### Submitting Code

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test your changes thoroughly
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Style

- Follow existing code style and conventions
- Use meaningful variable and function names
- Add comments for complex logic
- Update documentation if adding new features

### Testing

Before submitting:

1. Test with an actual Stagg EKG+ kettle
2. Verify all entities work correctly
3. Check that temperature unit switching works
4. Test power on/off functionality
5. Ensure no errors in Home Assistant logs

### Documentation

If you add features, please update:

- README.md with usage examples
- KETTLE_SPECS.md if discovering new technical details
- PYTHON_API_EXAMPLES.md if adding API methods
- CHANGELOG.md with your changes

## Development Setup

1. Clone the repository
2. Copy `custom_components/stagg_ekg` to your HA config
3. Restart Home Assistant
4. Add the integration with your kettle's IP

## Questions?

Feel free to open an issue for questions or discussions.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
