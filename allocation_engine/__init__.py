"""
AVCRI Hospital Therapy Allocation Engine.

Layered modular architecture:
- Layer 1A: allocation_engine.core.primitives (leaf utilities & persistence; zero service imports)
- Layer 1B: allocation_engine.core.allocators (shared allocators)
- Layer 2:  allocation_engine.rules (therapy-specific business rules)
- Layer 3:  allocation_engine.scheduling & allocation_engine.rescheduling (independent orchestrators)
"""
