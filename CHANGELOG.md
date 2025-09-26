# Changelog

All notable changes to Ryan's Viral Pattern Detector will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-09-26

### Added
- **Statistical export columns** for better VA analysis
  - `trimmed_mean_views` column showing account baseline performance
  - `standard_deviations_away` column quantifying viral performance
- **Enhanced export sorting** by viral performance (highest first)
- **Null value handling** for accounts with insufficient data (< 3 posts)
- **Comprehensive documentation** in README with statistical methodology

### Changed
- **Export format enhancement** - Both outliers and review exports now include statistical context
- **Improved data presentation** - Accounts without sufficient data show null instead of confusing zeros
- **Better sorting logic** - Statistical outliers prioritized, insufficient data accounts placed last

### Fixed
- **Statistical calculation edge cases** - Proper handling when accounts have fewer than 3 posts
- **Export column formatting** - Consistent rounding and null value representation

## [1.0.0] - 2025-09-26

### Added
- **Complete Instagram scraping pipeline** via Apify integration
- **Statistical analysis engine** with trimmed mean/standard deviation methodology
- **Database management** with Supabase for data persistence
- **Multi-format export system** (CSV for VA review, JSONL for AI analysis)
- **Review workflow** with import/export for human decisions
- **CLI interface** with 5 main commands (scrape, analyze, export, import-review, upload-videos)
- **Docker deployment** support for Railway and other platforms
- **Comprehensive error handling** with retry logic and graceful degradation
- **Progress tracking** with tqdm progress bars for long operations
- **Data validation** with input sanitization and type checking
- **Non-overwrite policy** protecting human/AI review fields

### Database Schema
- **accounts table** - Instagram account handles
- **posts table** - Complete post data with metrics (views, likes, comments, etc.)
- **post_review table** - Review workflow with human/AI fields
- **account_summaries table** - Per-account statistical summaries

### Technical Features
- **Apify actor integration** using shu8hvrXbJbY3Eb9W for Instagram scraping
- **Configurable outlier detection** with customizable standard deviation thresholds
- **Batch processing** for database operations (1000 record chunks)
- **Timeout handling** for external API calls (300s default)
- **Concurrent request management** (5 concurrent max)
- **Environment-based configuration** with comprehensive .env support

### Documentation
- **Complete README** with setup, usage, and troubleshooting
- **API documentation** for all CLI commands and parameters
- **Workflow examples** for common use cases
- **Test data** with sample inputs and expected outputs
- **Docker deployment** instructions for production use

### Supported Operations
- **Instagram scraping** (reels, posts, tagged content)
- **Statistical analysis** (per-account baselines and outlier detection)
- **Data export** (video download lists, VA review sheets, AI batch files)
- **Review import** (VA decision integration with non-overwrite protection)
- **Video upload** (optional Supabase Storage integration)

## Development Notes

### Architecture Decisions
- **Trimmed statistics approach** chosen for robust outlier detection
- **Supabase** selected for managed database with excellent API
- **Click framework** for CLI to provide professional command-line interface
- **Pandas** for data manipulation and CSV operations
- **Tenacity** for retry logic on external API calls

### Performance Optimizations
- **Batch database operations** to handle large datasets efficiently
- **Progress tracking** for user feedback during long operations
- **Memory-efficient processing** with streaming for large data sets
- **Concurrent API calls** where appropriate to reduce total execution time

### Security Considerations
- **Input validation** on all user-provided data
- **SQL injection protection** through parameterized queries
- **API key security** with environment variable configuration
- **Data privacy** with local processing and no third-party data sharing

### Quality Assurance
- **Comprehensive error handling** with graceful degradation
- **Data integrity checks** throughout the pipeline
- **Validation rules** for all data types and ranges
- **Non-destructive operations** with audit trails

### Future Roadmap
- Additional social media platform support
- Real-time monitoring capabilities
- Advanced AI integration for content analysis
- Enhanced statistical models for prediction
- Web dashboard for non-technical users