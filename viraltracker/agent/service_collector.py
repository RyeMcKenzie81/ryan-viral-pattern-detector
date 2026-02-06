"""
Service Collector - Discover and catalog all services for documentation.

This module discovers services from the viraltracker/services/ directory
and extracts metadata for documentation and the Services Catalog UI.

Usage:
    from viraltracker.agent.service_collector import get_all_services

    services = get_all_services()
    for service_name, service_info in services.items():
        print(f"{service_name}: {service_info.description}")
"""

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, get_type_hints

logger = logging.getLogger(__name__)


@dataclass
class ParameterInfo:
    """Information about a method parameter."""
    name: str
    type_str: str
    default: str
    required: bool


@dataclass
class MethodInfo:
    """Information about a service method."""
    name: str
    signature: str
    docstring: str
    parameters: List[ParameterInfo]
    return_type: str
    is_async: bool


@dataclass
class ServiceInfo:
    """Information about a service class."""
    name: str
    module_path: str
    file_path: str
    description: str
    full_docstring: str
    category: str
    methods: List[MethodInfo] = field(default_factory=list)
    method_count: int = 0


# Category mappings based on service name patterns
CATEGORY_PATTERNS = {
    # Platform services
    'twitter': 'Platform',
    'tiktok': 'Platform',
    'youtube': 'Platform',
    'facebook': 'Platform',
    'meta_ads': 'Platform',

    # AI/LLM services
    'gemini': 'AI/LLM',
    'veo': 'AI/LLM',
    'elevenlabs': 'AI/LLM',
    'els_parser': 'AI/LLM',

    # Content creation
    'ad_creation': 'Content Creation',
    'copy_scaffold': 'Content Creation',
    'audio_production': 'Content Creation',
    'template': 'Content Creation',
    'avatar': 'Content Creation',

    # Research & Analysis
    'angle_candidate': 'Research & Analysis',
    'pattern_discovery': 'Research & Analysis',
    'reddit_sentiment': 'Research & Analysis',
    'amazon': 'Research & Analysis',
    'brand_research': 'Research & Analysis',
    'competitor': 'Research & Analysis',
    'belief_analysis': 'Research & Analysis',
    'ad_analysis': 'Research & Analysis',

    # Business Logic
    'planning': 'Business Logic',
    'persona': 'Business Logic',
    'product_context': 'Business Logic',
    'product_offer': 'Business Logic',
    'product_url': 'Business Logic',

    # Utility
    'ffmpeg': 'Utility',
    'stats': 'Utility',
    'comment': 'Utility',
    'comparison': 'Utility',

    # Integration
    'apify': 'Integration',
    'slack': 'Integration',
    'email': 'Integration',
    'scraping': 'Integration',
    'web_scraping': 'Integration',
    'ad_scraping': 'Integration',
    'client_onboarding': 'Integration',

    # Comic Video
    'comic': 'Comic Video',

    # Content Pipeline
    'content_pipeline': 'Content Pipeline',
    'topic': 'Content Pipeline',
    'script': 'Content Pipeline',
    'asset': 'Content Pipeline',
    'handoff': 'Content Pipeline',
    'sora': 'Content Pipeline',

    # Knowledge Base
    'knowledge': 'Knowledge Base',
    'doc': 'Knowledge Base',
}


def categorize_service(service_name: str, module_path: str) -> str:
    """
    Auto-categorize a service based on its name and module path.

    Args:
        service_name: The service class name
        module_path: The full module path

    Returns:
        Category string
    """
    # Check module path for subdirectory clues
    if 'comic_video' in module_path:
        return 'Comic Video'
    if 'content_pipeline' in module_path:
        return 'Content Pipeline'
    if 'knowledge_base' in module_path:
        return 'Knowledge Base'

    # Normalize service name for matching
    name_lower = service_name.lower().replace('service', '').strip('_')

    for pattern, category in CATEGORY_PATTERNS.items():
        if pattern in name_lower or pattern in module_path.lower():
            return category

    # Check if it's a models file
    if 'models' in module_path.lower():
        return 'Models'

    return 'Other'


def extract_parameter_info(param: inspect.Parameter) -> Optional[ParameterInfo]:
    """Extract parameter information from an inspect.Parameter object."""
    if param.name in ['self', 'cls']:
        return None

    # Get type annotation
    if param.annotation == inspect.Parameter.empty:
        type_str = "Any"
    else:
        type_str = str(param.annotation)
        # Clean up type string
        type_str = type_str.replace('typing.', '').replace('<class \'', '').replace('\'>', '')

    # Get default value
    if param.default == inspect.Parameter.empty:
        default_str = "required"
        required = True
    else:
        default_str = repr(param.default)
        required = False

    return ParameterInfo(
        name=param.name,
        type_str=type_str,
        default=default_str,
        required=required
    )


def extract_return_type(method) -> str:
    """Extract return type annotation from a method."""
    try:
        sig = inspect.signature(method)
        if sig.return_annotation == inspect.Signature.empty:
            return "None"

        return_str = str(sig.return_annotation)
        return return_str.replace('typing.', '').replace('<class \'', '').replace('\'>', '')
    except Exception:
        return "None"


def extract_method_info(name: str, method) -> Optional[MethodInfo]:
    """
    Extract method information from a method object.

    Args:
        name: Method name
        method: Method object

    Returns:
        MethodInfo or None if extraction fails
    """
    try:
        # Get signature
        sig = inspect.signature(method)
        signature_str = str(sig)

        # Get docstring
        docstring = inspect.getdoc(method) or "No documentation available"

        # Get parameters
        parameters = []
        for param_name, param in sig.parameters.items():
            param_info = extract_parameter_info(param)
            if param_info:
                parameters.append(param_info)

        # Get return type
        return_type = extract_return_type(method)

        # Check if async
        is_async = inspect.iscoroutinefunction(method)

        return MethodInfo(
            name=name,
            signature=signature_str,
            docstring=docstring,
            parameters=parameters,
            return_type=return_type,
            is_async=is_async
        )
    except Exception as e:
        logger.debug(f"Could not extract method info for {name}: {e}")
        return None


def extract_service_info(service_class, module_path: str, file_path: str) -> ServiceInfo:
    """
    Extract information from a service class.

    Args:
        service_class: The service class object
        module_path: Full import path
        file_path: File path to the service

    Returns:
        ServiceInfo dataclass
    """
    # Get class docstring
    full_docstring = inspect.getdoc(service_class) or ""
    description = full_docstring.split('\n')[0] if full_docstring else "No description"

    # Get class name
    name = service_class.__name__

    # Categorize
    category = categorize_service(name, module_path)

    # Extract methods
    methods = []
    for method_name, method in inspect.getmembers(service_class):
        # Skip magic methods and private methods
        if method_name.startswith('_'):
            continue

        # Check if it's a callable method
        if not callable(method):
            continue

        # Check if it's actually defined on this class (not inherited from object)
        if hasattr(method, '__self__') or inspect.ismethod(method) or inspect.isfunction(method):
            method_info = extract_method_info(method_name, method)
            if method_info:
                methods.append(method_info)

    # Sort methods alphabetically
    methods.sort(key=lambda m: m.name)

    return ServiceInfo(
        name=name,
        module_path=module_path,
        file_path=file_path,
        description=description,
        full_docstring=full_docstring,
        category=category,
        methods=methods,
        method_count=len(methods)
    )


def discover_services_in_directory(directory: Path, base_module: str) -> Dict[str, ServiceInfo]:
    """
    Recursively discover all service classes in a directory.

    Args:
        directory: Directory to search
        base_module: Base module path

    Returns:
        Dictionary of service name -> ServiceInfo
    """
    services = {}

    for item in directory.iterdir():
        if item.is_dir():
            # Recurse into subdirectories (but skip __pycache__)
            if item.name.startswith('__'):
                continue

            sub_module = f"{base_module}.{item.name}"
            sub_services = discover_services_in_directory(item, sub_module)
            services.update(sub_services)

        elif item.suffix == '.py' and not item.name.startswith('_'):
            # Skip __init__.py, but process all other .py files
            module_name = item.stem
            full_module = f"{base_module}.{module_name}"

            try:
                # Import the module
                module = importlib.import_module(full_module)

                # Find service classes in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Check if it's defined in this module (not imported)
                    if obj.__module__ != full_module:
                        continue

                    # Check if it looks like a service class
                    if name.endswith('Service') or 'service' in module_name.lower():
                        # Extract service info
                        service_info = extract_service_info(obj, full_module, str(item))
                        services[name] = service_info
                        logger.debug(f"Discovered service: {name}")

            except Exception as e:
                logger.debug(f"Could not import {full_module}: {e}")

    return services


def get_all_services() -> Dict[str, ServiceInfo]:
    """
    Discover all services from viraltracker/services/.

    Returns:
        Dictionary mapping service names to ServiceInfo objects
    """
    # Find the services directory
    import viraltracker.services as services_pkg
    services_dir = Path(services_pkg.__file__).parent

    logger.info(f"Discovering services in {services_dir}")

    services = discover_services_in_directory(services_dir, "viraltracker.services")

    logger.info(f"Discovered {len(services)} services")

    return services


def get_services_by_category() -> Dict[str, List[ServiceInfo]]:
    """
    Organize services by category.

    Returns:
        Dictionary mapping categories to lists of ServiceInfo objects
    """
    services = get_all_services()
    categories = {}

    for service_info in services.values():
        category = service_info.category
        if category not in categories:
            categories[category] = []
        categories[category].append(service_info)

    # Sort services within each category by name
    for category in categories:
        categories[category].sort(key=lambda s: s.name)

    return categories


def get_service_stats() -> Dict[str, Any]:
    """
    Get statistics about discovered services.

    Returns:
        Dictionary with service statistics
    """
    services = get_all_services()
    categories = get_services_by_category()

    total_methods = sum(s.method_count for s in services.values())
    async_methods = sum(
        sum(1 for m in s.methods if m.is_async)
        for s in services.values()
    )

    return {
        'total_services': len(services),
        'total_methods': total_methods,
        'async_methods': async_methods,
        'sync_methods': total_methods - async_methods,
        'categories': len(categories),
        'avg_methods_per_service': round(total_methods / len(services), 1) if services else 0,
        'category_breakdown': {cat: len(svcs) for cat, svcs in categories.items()}
    }
