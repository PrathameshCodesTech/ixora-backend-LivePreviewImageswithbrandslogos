#!/usr/bin/env python3
"""
Stress Test Script for Concurrent Image Generation
Tests system performance under high concurrent load
"""

import asyncio
import aiohttp
import time
import json
import random
from dataclasses import dataclass
from typing import List, Dict, Any
import threading
import queue
import statistics

@dataclass
class TestResult:
    """Store test result data"""
    request_id: int
    start_time: float
    end_time: float
    duration: float
    status_code: int
    success: bool
    error_message: str = None
    task_id: str = None

class ConcurrentImageTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[TestResult] = []
        self.results_lock = threading.Lock()
        
        # Test data - replace with your actual data
        self.test_templates = [1]  # Your template IDs
        self.test_doctors = []  # Will be populated
        self.test_brands = [1, 2]  # Your brand IDs
        
    async def get_test_data(self):
        """Setup test data without API calls"""
        # Use hardcoded test data to avoid authentication issues
        self.test_doctors = list(range(1, 21))  # Will create new doctors as needed
        print(f"Using {len(self.test_doctors)} test doctor IDs")

    async def generate_single_image(self, session: aiohttp.ClientSession, request_id: int) -> TestResult:
        """Generate a single image and track performance"""
        start_time = time.time()
        
        # Randomize test data for variety
        template_id = random.choice(self.test_templates)
        doctor_id = random.choice(self.test_doctors)
        selected_brands = random.sample(self.test_brands, k=random.randint(1, len(self.test_brands)))
        
        payload = {
            "template_id": template_id,
            "name": f"Test Doctor {request_id}",
            "mobile": f"12345{request_id:05d}",  # Unique mobile numbers
            "employee_id": "EMP001",  # Your created employee
            "selected_brands": selected_brands,
            "content_data": {
                "doctor_name": f"Test Doctor {request_id}",
                "doctor_clinic": f"Test Clinic {request_id}",
                "doctor_city": "Test City", 
                "doctor_state": "Test State",
                "doctor_specialization": "Test Specialization"
            }
        }
        
        try:
            async with session.post(
                f"{self.base_url}/api/generate-image/",
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                end_time = time.time()
                duration = end_time - start_time
                
                response_data = await response.json()
                task_id = response_data.get('task_id')
                
                result = TestResult(
                    request_id=request_id,
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    status_code=response.status,
                    success=response.status in [200, 201],
                    task_id=task_id
                )
                
                return result
                
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            
            result = TestResult(
                request_id=request_id,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                status_code=0,
                success=False,
                error_message=str(e)
            )
            
            return result

    async def check_task_completion(self, session: aiohttp.ClientSession, task_id: str) -> Dict[str, Any]:
        """Check if a task has completed"""
        try:
            async with session.get(f"{self.base_url}/api/task-status/{task_id}/") as response:
                if response.status == 200:
                    return await response.json()
                return {"status": "error", "error": f"HTTP {response.status}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def run_concurrent_test(self, num_requests: int = 100, concurrent_limit: int = 20):
        """Run concurrent image generation test"""
        print(f"Starting concurrent test: {num_requests} requests, {concurrent_limit} concurrent")
        print("=" * 60)
        
        # Get test data first
        await self.get_test_data()
        
        # Create semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(concurrent_limit)
        
        async def bounded_request(request_id: int):
            async with semaphore:
                async with aiohttp.ClientSession() as session:
                    return await self.generate_single_image(session, request_id)
        
        # Start all requests
        test_start_time = time.time()
        print(f"Launching {num_requests} concurrent requests...")
        
        tasks = [bounded_request(i) for i in range(num_requests)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        test_end_time = time.time()
        total_test_time = test_end_time - test_start_time
        
        # Process results
        successful_results = []
        failed_results = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_results.append(str(result))
            elif result.success:
                successful_results.append(result)
            else:
                failed_results.append(f"Request {result.request_id}: {result.error_message}")
        
        # Print immediate results
        self.print_test_summary(successful_results, failed_results, total_test_time)
        
        # Check task completion for successful requests
        if successful_results:
            await self.monitor_task_completion(successful_results)
        
        return successful_results, failed_results

    async def monitor_task_completion(self, successful_results: List[TestResult]):
        """Monitor completion of background tasks"""
        print("\nMonitoring task completion...")
        print("-" * 40)
        
        task_ids = [r.task_id for r in successful_results if r.task_id]
        completed_tasks = []
        failed_tasks = []
        
        start_monitoring = time.time()
        timeout = 300  # 5 minutes timeout
        
        async with aiohttp.ClientSession() as session:
            while task_ids and (time.time() - start_monitoring) < timeout:
                remaining_tasks = []
                
                for task_id in task_ids:
                    status_data = await self.check_task_completion(session, task_id)
                    
                    if status_data.get("status") == "completed":
                        completed_tasks.append(task_id)
                        print(f"✓ Task {task_id[:8]}... completed")
                    elif status_data.get("status") == "failed":
                        failed_tasks.append(task_id)
                        print(f"✗ Task {task_id[:8]}... failed")
                    else:
                        remaining_tasks.append(task_id)
                
                task_ids = remaining_tasks
                
                if task_ids:
                    await asyncio.sleep(2)  # Check every 2 seconds
        
        # Final task completion summary
        total_monitoring_time = time.time() - start_monitoring
        print(f"\nTask Completion Summary (after {total_monitoring_time:.1f}s):")
        print(f"✓ Completed: {len(completed_tasks)}")
        print(f"✗ Failed: {len(failed_tasks)}")
        print(f"⏳ Still processing: {len(task_ids)}")

    def print_test_summary(self, successful: List[TestResult], failed: List[str], total_time: float):
        """Print test performance summary"""
        print(f"\nSTRESS TEST RESULTS")
        print("=" * 60)
        print(f"Total test time: {total_time:.2f} seconds")
        print(f"Successful requests: {len(successful)}")
        print(f"Failed requests: {len(failed)}")
        print(f"Success rate: {len(successful)/(len(successful)+len(failed))*100:.1f}%")
        
        if successful:
            durations = [r.duration for r in successful]
            print(f"\nRequest Duration Stats:")
            print(f"  Average: {statistics.mean(durations):.3f}s")
            print(f"  Median: {statistics.median(durations):.3f}s")
            print(f"  Min: {min(durations):.3f}s")
            print(f"  Max: {max(durations):.3f}s")
            print(f"  Requests/second: {len(successful)/total_time:.2f}")
        
        if failed:
            print(f"\nFirst 5 Failures:")
            for error in failed[:5]:
                print(f"  - {error}")

    def monitor_system_resources(self):
        """Monitor system resources during test (requires psutil)"""
        try:
            import psutil
            process = psutil.Process()
            
            print(f"\nSystem Resources:")
            print(f"CPU Usage: {psutil.cpu_percent()}%")
            print(f"Memory Usage: {psutil.virtual_memory().percent}%")
            print(f"Available Memory: {psutil.virtual_memory().available / (1024**3):.1f} GB")
            
        except ImportError:
            print("Install psutil for system monitoring: pip install psutil")

# Test configurations
TEST_CONFIGS = {
    "light": {"requests": 10, "concurrent": 5},
    "medium": {"requests": 50, "concurrent": 10}, 
    "heavy": {"requests": 100, "concurrent": 20},
    "extreme": {"requests": 200, "concurrent": 50}
}

async def main():
    """Main test runner"""
    print("Concurrent Image Generation Stress Test")
    print("=" * 60)
    
    # Initialize tester
    tester = ConcurrentImageTester()
    tester.monitor_system_resources()
    
    # Ask user for test configuration
    print("\nSelect test intensity:")
    for name, config in TEST_CONFIGS.items():
        print(f"  {name}: {config['requests']} requests, {config['concurrent']} concurrent")
    
    test_type = input("\nEnter test type (light/medium/heavy/extreme): ").strip().lower()
    
    if test_type not in TEST_CONFIGS:
        print("Invalid test type, using 'medium'")
        test_type = "medium"
    
    config = TEST_CONFIGS[test_type]
    
    # Run the test
    try:
        successful, failed = await tester.run_concurrent_test(
            num_requests=config["requests"],
            concurrent_limit=config["concurrent"]
        )
        
        print(f"\nTest completed! Check your Celery worker logs for processing details.")
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"\nTest failed with error: {e}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())